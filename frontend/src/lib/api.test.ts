import { describe, expect, it, vi } from "vitest";
import { ApiError, buildUrl, createApi, readCookie, type ApiDeps } from "./api";

function jsonResponse(status: number, body: unknown, contentType = "application/json") {
  return new Response(body === undefined ? null : JSON.stringify(body), { status, headers: { "content-type": contentType } });
}

function deps(response: Response, opts: { cookie?: string; pathname?: string } = {}) {
  // Each call gets a fresh copy: a Response body can only be read once.
  const fetchMock = vi.fn<typeof fetch>(async () => response.clone());
  const assign = vi.fn();
  const d: ApiDeps = {
    fetch: fetchMock as unknown as typeof fetch,
    cookie: () => opts.cookie ?? "",
    location: () => ({ pathname: opts.pathname ?? "/users/", assign }),
  };
  return { d, fetchMock, assign };
}

describe("readCookie", () => {
  it("reads and decodes a named cookie", () => {
    expect(readCookie("veyra_csrf", "a=1; veyra_csrf=abc%3D%3D; b=2")).toBe("abc==");
    expect(readCookie("missing", "a=1")).toBeNull();
  });
});

describe("buildUrl", () => {
  it("prefixes the API base and drops empty query values", () => {
    expect(buildUrl("/users", { q: "", limit: 25, offset: 0, x: null })).toBe("/api/v1/users?limit=25&offset=0");
    expect(buildUrl("audit")).toBe("/api/v1/audit");
  });
});

describe("api client", () => {
  it("sends the CSRF header on mutations only", async () => {
    const { d, fetchMock } = deps(jsonResponse(200, { ok: true }), { cookie: "veyra_csrf=tok123" });
    const api = createApi(d);
    await api.post("/organizations", { name: "A" });
    const init = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect((init.headers as Record<string, string>)["X-CSRF-Token"]).toBe("tok123");
    expect(init.credentials).toBe("same-origin");
    expect(init.body).toBe(JSON.stringify({ name: "A" }));

    await api.get("/organizations");
    const getInit = fetchMock.mock.calls[1]?.[1] as RequestInit;
    expect((getInit.headers as Record<string, string>)["X-CSRF-Token"]).toBeUndefined();
  });

  it("parses RFC 9457 problem details into ApiError", async () => {
    const problem = {
      title: "Validation failed", status: 422, detail: "One or more fields are invalid.", code: "validation_failed",
      request_id: "req-1", errors: [{ field: "slug", message: "bad slug" }, { field: "slug", message: "second" }],
    };
    const { d } = deps(jsonResponse(422, problem, "application/problem+json"));
    const err = await createApi(d).post("/organizations", {}).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    const e = err as ApiError;
    expect(e.status).toBe(422);
    expect(e.code).toBe("validation_failed");
    expect(e.requestId).toBe("req-1");
    expect(e.message).toBe("One or more fields are invalid.");
    expect(e.fieldErrors()).toEqual({ slug: "bad slug" });
  });

  it("handles non-JSON error bodies", async () => {
    const { d } = deps(new Response("<html>Bad gateway</html>", { status: 502 }));
    const e = (await createApi(d).get("/system/health").catch((x: unknown) => x)) as ApiError;
    expect(e.status).toBe(502);
    expect(e.title).toMatch(/not responding/);
  });

  it("redirects to sign-in on 401 outside auth pages", async () => {
    const { d, assign } = deps(jsonResponse(401, { title: "Unauthorized" }), { pathname: "/users/" });
    await expect(createApi(d).get("/users")).rejects.toBeInstanceOf(ApiError);
    expect(assign).toHaveBeenCalledWith("/login/?next=%2Fusers%2F");
  });

  it("does not redirect on 401 from the login page or when disabled", async () => {
    const a = deps(jsonResponse(401, { title: "Unauthorized" }), { pathname: "/login/" });
    await createApi(a.d).get("/auth/session").catch(() => undefined);
    expect(a.assign).not.toHaveBeenCalled();
    const b = deps(jsonResponse(401, { title: "Unauthorized" }), { pathname: "/" });
    await createApi(b.d).get("/auth/session", undefined, { noRedirect: true }).catch(() => undefined);
    expect(b.assign).not.toHaveBeenCalled();
  });

  it("reports network failures as ApiError with status 0", async () => {
    const d: ApiDeps = {
      fetch: (async () => { throw new TypeError("fetch failed"); }) as unknown as typeof fetch,
      cookie: () => "",
      location: () => null,
    };
    const e = (await createApi(d).get("/x").catch((x: unknown) => x)) as ApiError;
    expect(e.status).toBe(0);
    expect(e.code).toBe("network_error");
  });
});
