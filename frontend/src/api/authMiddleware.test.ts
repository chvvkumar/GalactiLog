import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { authMiddleware } from "./authMiddleware";

// authMiddleware defers the actual refresh POST to the shared
// authRefresh.refreshSession() primitive (covered by authRefresh.test.ts).
// These tests focus on middleware-specific behavior: retry-once on success,
// skipping refresh for the auth endpoints themselves, and dispatching
// auth:expired on terminal failure.
describe("authMiddleware", () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    globalThis.fetch = vi.fn();
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  function makeRequest(path: string, init?: RequestInit): Request {
    return new Request(`http://localhost/api${path}`, init);
  }

  it("retries the original request once after a successful refresh", async () => {
    // First call: the /auth/refresh POST triggered by refreshSession().
    // Second call: the retried original request.
    vi.mocked(globalThis.fetch)
      .mockResolvedValueOnce(new Response(null, { status: 200 })) // /auth/refresh
      .mockResolvedValueOnce(new Response("ok", { status: 200 })); // retried request

    const request = makeRequest("/targets");
    await authMiddleware.onRequest!({ request } as any);

    const result = await authMiddleware.onResponse!({
      request,
      response: new Response(null, { status: 401 }),
    } as any);

    expect(result).toBeInstanceOf(Response);
    expect(await (result as Response).text()).toBe("ok");
    expect(globalThis.fetch).toHaveBeenCalledTimes(2);
  });

  it("dispatches auth:expired and does not retry on terminal refresh failure", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(new Response(null, { status: 401 })); // /auth/refresh fails

    const dispatchSpy = vi.spyOn(window, "dispatchEvent");

    const request = makeRequest("/targets");
    await authMiddleware.onRequest!({ request } as any);

    const originalResponse = new Response(null, { status: 401 });
    const result = await authMiddleware.onResponse!({
      request,
      response: originalResponse,
    } as any);

    expect(result).toBe(originalResponse);
    expect(globalThis.fetch).toHaveBeenCalledTimes(1); // only the refresh attempt, no retry
    expect(dispatchSpy).toHaveBeenCalledWith(expect.objectContaining({ type: "auth:expired" }));
  });

  it("does not attempt a refresh for a 401 on /auth/refresh itself", async () => {
    const request = makeRequest("/auth/refresh", { method: "POST" });
    await authMiddleware.onRequest!({ request } as any);

    const originalResponse = new Response(null, { status: 401 });
    const result = await authMiddleware.onResponse!({
      request,
      response: originalResponse,
    } as any);

    expect(result).toBe(originalResponse);
    expect(globalThis.fetch).not.toHaveBeenCalled();
  });

  it("does not attempt a refresh for a 401 on /auth/login itself", async () => {
    const request = makeRequest("/auth/login", { method: "POST" });
    await authMiddleware.onRequest!({ request } as any);

    const originalResponse = new Response(null, { status: 401 });
    const result = await authMiddleware.onResponse!({
      request,
      response: originalResponse,
    } as any);

    expect(result).toBe(originalResponse);
    expect(globalThis.fetch).not.toHaveBeenCalled();
  });

  it("passes through non-401 responses unchanged", async () => {
    const request = makeRequest("/targets");
    await authMiddleware.onRequest!({ request } as any);

    const originalResponse = new Response("fine", { status: 200 });
    const result = await authMiddleware.onResponse!({
      request,
      response: originalResponse,
    } as any);

    expect(result).toBe(originalResponse);
    expect(globalThis.fetch).not.toHaveBeenCalled();
  });

  it("dedupes two concurrent 401s across different requests into a single refresh", async () => {
    let resolveRefresh!: (r: Response) => void;
    vi.mocked(globalThis.fetch).mockImplementation((input: any) => {
      const url = typeof input === "string" ? input : input.url;
      if (url.includes("/auth/refresh")) {
        return new Promise((resolve) => {
          resolveRefresh = resolve;
        });
      }
      return Promise.resolve(new Response("retried", { status: 200 }));
    });

    const requestA = makeRequest("/targets");
    const requestB = makeRequest("/stats");
    await authMiddleware.onRequest!({ request: requestA } as any);
    await authMiddleware.onRequest!({ request: requestB } as any);

    const resultAPromise = authMiddleware.onResponse!({
      request: requestA,
      response: new Response(null, { status: 401 }),
    } as any);
    const resultBPromise = authMiddleware.onResponse!({
      request: requestB,
      response: new Response(null, { status: 401 }),
    } as any);

    // Only the single /auth/refresh POST should be in flight at this point.
    expect(vi.mocked(globalThis.fetch).mock.calls.filter((c) => String(c[0]).includes("/auth/refresh")).length).toBe(1);

    resolveRefresh(new Response(null, { status: 200 }));

    const [resultA, resultB] = await Promise.all([resultAPromise, resultBPromise]);
    expect(await (resultA as Response).text()).toBe("retried");
    expect(await (resultB as Response).text()).toBe("retried");
  });
});
