import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { refreshSession } from "./authRefresh";

describe("refreshSession", () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    globalThis.fetch = vi.fn();
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("dedupes concurrent callers into a single underlying fetch", async () => {
    let resolveFetch!: (r: Response) => void;
    vi.mocked(globalThis.fetch).mockReturnValueOnce(
      new Promise((resolve) => {
        resolveFetch = resolve;
      }),
    );

    const call1 = refreshSession();
    const call2 = refreshSession();

    // Both callers should be awaiting the same in-flight promise: only one
    // fetch should have been dispatched so far.
    expect(globalThis.fetch).toHaveBeenCalledTimes(1);

    resolveFetch(new Response(null, { status: 200 }));

    const [ok1, ok2] = await Promise.all([call1, call2]);
    expect(ok1).toBe(true);
    expect(ok2).toBe(true);
    expect(globalThis.fetch).toHaveBeenCalledTimes(1);
  });

  it("issues a new fetch for a call made after the previous refresh settled", async () => {
    vi.mocked(globalThis.fetch)
      .mockResolvedValueOnce(new Response(null, { status: 200 }))
      .mockResolvedValueOnce(new Response(null, { status: 200 }));

    await refreshSession();
    await refreshSession();

    expect(globalThis.fetch).toHaveBeenCalledTimes(2);
  });

  it("resolves false (without throwing) when the refresh endpoint returns a non-ok status", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(new Response(null, { status: 401 }));

    await expect(refreshSession()).resolves.toBe(false);
  });

  it("resolves false (without throwing) when the underlying fetch rejects", async () => {
    vi.mocked(globalThis.fetch).mockRejectedValueOnce(new Error("network down"));

    await expect(refreshSession()).resolves.toBe(false);
  });

  it("posts to /auth/refresh with same-origin credentials", async () => {
    vi.mocked(globalThis.fetch).mockResolvedValueOnce(new Response(null, { status: 200 }));

    await refreshSession();

    expect(globalThis.fetch).toHaveBeenCalledWith(
      expect.stringContaining("/auth/refresh"),
      expect.objectContaining({ method: "POST", credentials: "same-origin" }),
    );
  });
});
