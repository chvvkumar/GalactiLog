import { describe, it, expect } from "vitest";
import { unwrap, toApiError, ApiError } from "./unwrap";

// Reincarnates the intent of the old api/client.test.ts's ApiError-shape
// assertions (that file is removed in the T3 teardown slice once the last
// call site migrates) as coverage of the generated-client `unwrap` helper.
describe("unwrap", () => {
  it("returns data on a successful result", () => {
    const payload = { hello: "world" };
    const result = unwrap({
      data: payload,
      error: undefined,
      response: new Response(null, { status: 200 }),
    });
    expect(result).toEqual(payload);
  });

  it("throws an ApiError with the server detail on a 4xx error result", () => {
    expect(() =>
      unwrap({
        data: undefined,
        error: { detail: "Not found" },
        response: new Response(null, { status: 404 }),
      })
    ).toThrow(ApiError);

    try {
      unwrap({
        data: undefined,
        error: { detail: "Not found" },
        response: new Response(null, { status: 404 }),
      });
      expect.unreachable("unwrap should have thrown");
    } catch (err) {
      expect(err).toMatchObject({ name: "ApiError", status: 404, message: "Not found" });
    }
  });

  it("stringifies a non-string detail (e.g. FastAPI validation errors)", () => {
    const detail = [{ loc: ["body", "name"], msg: "field required" }];
    try {
      unwrap({
        data: undefined,
        error: { detail },
        response: new Response(null, { status: 422 }),
      });
      expect.unreachable("unwrap should have thrown");
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError);
      expect((err as ApiError).status).toBe(422);
      expect((err as ApiError).message).toBe(JSON.stringify(detail));
    }
  });

  it("falls back to a fixed per-status message when the error body has no detail", () => {
    try {
      unwrap({
        data: undefined,
        error: {},
        response: new Response(null, { status: 500 }),
      });
      expect.unreachable("unwrap should have thrown");
    } catch (err) {
      expect(err).toMatchObject({ status: 500, message: "Server error - please try again later" });
    }
  });

  it("throws on a non-2xx response even when error is undefined (empty-body infra failure)", () => {
    // openapi-fetch leaves `error` undefined for a non-2xx response with an
    // empty body (e.g. an nginx 502/504 during a backend restart). unwrap must
    // still throw -- matching old client.ts's unconditional throw on !resp.ok --
    // rather than returning undefined data as a fake success.
    try {
      unwrap({
        data: undefined,
        error: undefined,
        response: new Response(null, { status: 502 }),
      });
      expect.unreachable("unwrap should have thrown");
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError);
      expect((err as ApiError).status).toBe(502);
      // 502 is not in the per-status table -> generic status-only fallback.
      expect((err as ApiError).message).toBe("Something went wrong");
    }
  });

  it("does not throw on a 2xx response with undefined data (e.g. a 204 no-content success)", () => {
    const result = unwrap({
      data: undefined,
      error: undefined,
      response: new Response(null, { status: 204 }),
    });
    expect(result).toBeUndefined();
  });

  it("treats a present (non-undefined) falsy-ish error as an error case, even if null", () => {
    try {
      unwrap({
        data: undefined,
        error: null,
        response: new Response(null, { status: 418 }),
      });
      expect.unreachable("unwrap should have thrown");
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError);
      expect((err as ApiError).status).toBe(418);
      expect((err as ApiError).message).toBe("Something went wrong");
    }
  });

  it("ApiError is an instance of Error and carries status + message", () => {
    const err = new ApiError(400, "bad request");
    expect(err).toBeInstanceOf(Error);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(400);
    expect(err.message).toBe("bad request");
  });

  it("toApiError is the direct builder used internally by unwrap", () => {
    const err = toApiError({ detail: "Permission denied" }, 403);
    expect(err.status).toBe(403);
    expect(err.message).toBe("Permission denied");
  });
});
