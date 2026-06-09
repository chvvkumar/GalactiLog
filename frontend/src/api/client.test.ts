import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { fetchJson, ApiError } from "./client";

describe("fetchJson", () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    // Reset any module-level refresh state between tests by resetting fetch
    globalThis.fetch = vi.fn();
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("returns parsed JSON on a successful response", async () => {
    const payload = { hello: "world" };
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(
      new Response(JSON.stringify(payload), { status: 200 })
    );

    const result = await fetchJson<{ hello: string }>("/test");
    expect(result).toEqual(payload);
  });

  it("throws ApiError with the server detail on a 4xx response", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "Not found" }), { status: 404 })
    );

    await expect(fetchJson("/missing")).rejects.toMatchObject({
      name: "ApiError",
      status: 404,
      message: "Not found",
    });
  });

  it("throws ApiError with fallback message when body is not JSON", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(
      new Response("Internal Server Error", { status: 500 })
    );

    await expect(fetchJson("/err")).rejects.toMatchObject({
      name: "ApiError",
      status: 500,
    });
  });

  it("ApiError is an instance of Error", async () => {
    const err = new ApiError(400, "bad request");
    expect(err).toBeInstanceOf(Error);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(400);
    expect(err.message).toBe("bad request");
  });
});
