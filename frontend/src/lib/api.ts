// SPDX-License-Identifier: AGPL-3.0-or-later
/**
 * Typed client for the Veyra management API (same origin, /api/v1).
 *
 * - Cookies carry the session; mutations echo the `veyra_csrf` cookie in the
 *   X-CSRF-Token header (double-submit CSRF protection).
 * - Errors are RFC 9457 problem details and surface as ApiError.
 * - A 401 outside the sign-in and setup pages redirects to /login/.
 */

export const API_BASE = "/api/v1";
export const CSRF_COOKIE = "veyra_csrf";
export const CSRF_HEADER = "X-CSRF-Token";

export interface FieldError {
  field?: string;
  message: string;
  type?: string;
}

export interface Problem {
  type?: string;
  title?: string;
  status?: number;
  detail?: string;
  code?: string;
  instance?: string;
  request_id?: string | null;
  errors?: FieldError[];
}

export class ApiError extends Error {
  readonly status: number;
  readonly title: string;
  readonly detail?: string;
  readonly code?: string;
  readonly requestId?: string;
  readonly errors: FieldError[];

  constructor(status: number, problem: Problem) {
    super(problem.detail || problem.title || `Request failed (${status})`);
    this.name = "ApiError";
    this.status = status;
    this.title = problem.title || "Request failed";
    this.detail = problem.detail;
    this.code = problem.code;
    this.requestId = problem.request_id ?? undefined;
    this.errors = Array.isArray(problem.errors) ? problem.errors : [];
  }

  /** Field errors keyed by field path (e.g. "administrator.password"). */
  fieldErrors(): Record<string, string> {
    const out: Record<string, string> = {};
    for (const e of this.errors) {
      if (e.field && !(e.field in out)) out[e.field] = e.message;
    }
    return out;
  }
}

export function readCookie(name: string, cookieString?: string): string | null {
  const source = cookieString ?? (typeof document !== "undefined" ? document.cookie : "");
  for (const part of source.split(";")) {
    const [k, ...rest] = part.trim().split("=");
    if (k === name) return decodeURIComponent(rest.join("="));
  }
  return null;
}

const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);
const AUTH_FREE_PATHS = ["/login", "/setup", "/reset-password", "/forgot-password"];

export interface ApiOptions {
  method?: string;
  body?: unknown;
  /** Multipart form data (file uploads); sent as-is, no JSON encoding. */
  form?: FormData;
  query?: Record<string, string | number | boolean | null | undefined>;
  /** Do not redirect to the sign-in page on 401 (used by the session probe). */
  noRedirect?: boolean;
  signal?: AbortSignal;
  /** Return the body as text (CSV downloads) instead of parsing JSON. */
  raw?: boolean;
}

export interface ApiDeps {
  fetch: typeof fetch;
  cookie: () => string;
  location: () => { pathname: string; assign: (url: string) => void } | null;
}

const defaultDeps: ApiDeps = {
  fetch: (...args) => fetch(...args),
  cookie: () => (typeof document !== "undefined" ? document.cookie : ""),
  location: () =>
    typeof window !== "undefined"
      ? { pathname: window.location.pathname, assign: (u: string) => window.location.assign(u) }
      : null,
};

export function buildUrl(path: string, query?: ApiOptions["query"]): string {
  const url = `${API_BASE}${path.startsWith("/") ? path : `/${path}`}`;
  if (!query) return url;
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) {
    if (v === undefined || v === null || v === "") continue;
    params.set(k, String(v));
  }
  const qs = params.toString();
  return qs ? `${url}?${qs}` : url;
}

export async function parseProblem(res: Response): Promise<Problem> {
  const text = await res.text().catch(() => "");
  if (text) {
    try {
      const data = JSON.parse(text) as unknown;
      if (data && typeof data === "object") return data as Problem;
    } catch {
      /* not JSON */
    }
  }
  return {
    status: res.status,
    title: res.status === 502 || res.status === 503 || res.status === 504
      ? "The Veyra service is not responding"
      : res.statusText || "Request failed",
  };
}

export function createApi(deps: ApiDeps = defaultDeps) {
  async function request<T>(path: string, opts: ApiOptions = {}): Promise<T> {
    const method = (opts.method ?? (opts.body !== undefined ? "POST" : "GET")).toUpperCase();
    const headers: Record<string, string> = { Accept: "application/json" };
    if (opts.body !== undefined && !opts.form) headers["Content-Type"] = "application/json";
    if (!SAFE_METHODS.has(method)) {
      const csrf = readCookie(CSRF_COOKIE, deps.cookie());
      if (csrf) headers[CSRF_HEADER] = csrf;
    }
    let res: Response;
    try {
      res = await deps.fetch(buildUrl(path, opts.query), {
        method,
        headers,
        credentials: "same-origin",
        body: opts.form ?? (opts.body !== undefined ? JSON.stringify(opts.body) : undefined),
        signal: opts.signal,
      });
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") throw err;
      throw new ApiError(0, {
        title: "Cannot reach Veyra",
        detail: "The server could not be reached. Check your network connection and try again.",
        code: "network_error",
      });
    }
    if (!res.ok) {
      const problem = await parseProblem(res);
      // Not signed in, or a second factor still pending: back to the sign-in page.
      if ((res.status === 401 || (res.status === 403 && problem.code === "mfa_required")) && !opts.noRedirect) {
        const loc = deps.location();
        if (loc && !AUTH_FREE_PATHS.some((p) => loc.pathname.startsWith(p))) {
          loc.assign(`/login/?next=${encodeURIComponent(loc.pathname)}`);
        }
      }
      throw new ApiError(res.status, problem);
    }
    if (res.status === 204) return undefined as T;
    const text = await res.text();
    if (opts.raw) return text as T;
    return (text ? JSON.parse(text) : undefined) as T;
  }

  return {
    request,
    get: <T>(path: string, query?: ApiOptions["query"], opts: Omit<ApiOptions, "query"> = {}) =>
      request<T>(path, { ...opts, query, method: "GET" }),
    post: <T>(path: string, body?: unknown, opts: ApiOptions = {}) =>
      request<T>(path, { ...opts, method: "POST", body: body ?? {} }),
    put: <T>(path: string, body: unknown) => request<T>(path, { method: "PUT", body }),
    patch: <T>(path: string, body: unknown) => request<T>(path, { method: "PATCH", body }),
    del: <T>(path: string, query?: ApiOptions["query"]) => request<T>(path, { method: "DELETE", query }),
    /** Multipart upload (POST by default). */
    upload: <T>(path: string, form: FormData, method: "POST" | "PUT" = "POST") => request<T>(path, { method, form }),
  };
}

export const api = createApi();

export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.detail || err.title;
  if (err instanceof Error) return err.message;
  return "Something went wrong.";
}
