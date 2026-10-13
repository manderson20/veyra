// SPDX-License-Identifier: AGPL-3.0-or-later
/** Minimal HTTP client for the Veyra API with bearer authentication and
 * RFC 9457 problem parsing. */

export interface FieldError {
  field?: string;
  message: string;
  type?: string;
}

export interface ProblemDetails {
  type?: string;
  title?: string;
  status?: number;
  detail?: string;
  code?: string;
  errors?: FieldError[];
  request_id?: string | null;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly detail: string;
  readonly errors: FieldError[];

  constructor(status: number, code: string, detail: string, errors: FieldError[] = []) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.detail = detail;
    this.errors = errors;
  }
}

/** The token was rejected (401): the caller must sign in again. */
export class SignedOut extends Error {
  constructor(message = "Your sign-in has expired. Sign in again.") {
    super(message);
    this.name = "SignedOut";
  }
}

export interface JsonResponse<T> {
  status: number;
  body: T;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function parseFieldErrors(value: unknown): FieldError[] {
  if (!Array.isArray(value)) {
    return [];
  }
  const out: FieldError[] = [];
  for (const item of value) {
    if (isRecord(item) && typeof item.message === "string") {
      out.push({
        message: item.message,
        ...(typeof item.field === "string" ? { field: item.field } : {}),
        ...(typeof item.type === "string" ? { type: item.type } : {}),
      });
    }
  }
  return out;
}

/** Build an ApiError from a non-2xx response, tolerating non-JSON bodies. */
export async function problemFrom(response: Response): Promise<ApiError> {
  let data: unknown = null;
  try {
    data = await response.json();
  } catch {
    data = null;
  }
  const problem: ProblemDetails = isRecord(data) ? (data as ProblemDetails) : {};
  const code = problem.code ?? `http_${response.status}`;
  const detail =
    problem.detail ?? problem.title ?? `The server answered ${response.status} ${response.statusText}`;
  return new ApiError(response.status, code, detail, parseFieldErrors(problem.errors));
}

/** Normalise what the user typed into `https://host[:port]` without a path. */
export function normalizeServerUrl(input: string): string | null {
  let text = input.trim();
  if (text === "") {
    return null;
  }
  if (!/^[a-z]+:\/\//i.test(text)) {
    text = `https://${text}`;
  }
  let url: URL;
  try {
    url = new URL(text);
  } catch {
    return null;
  }
  if (url.protocol !== "https:" || url.hostname === "") {
    return null;
  }
  return url.origin;
}

export class VeyraClient {
  readonly baseUrl: string;
  token: string | null;
  private readonly onSignedOut: (() => Promise<void> | void) | undefined;

  constructor(baseUrl: string, token: string | null, onSignedOut?: () => Promise<void> | void) {
    this.baseUrl = baseUrl.replace(/\/+$/, "");
    this.token = token;
    this.onSignedOut = onSignedOut;
  }

  url(path: string): string {
    return `${this.baseUrl}${path.startsWith("/") ? path : `/${path}`}`;
  }

  /** Perform a request and return the status with the parsed JSON body
   * (`undefined` for 204). Throws ApiError on non-2xx, SignedOut on 401
   * while a token is held. */
  async fetchResponse<T>(path: string, init: RequestInit = {}): Promise<JsonResponse<T>> {
    const headers = new Headers(init.headers);
    headers.set("Accept", "application/json, application/problem+json");
    if (init.body !== undefined && init.body !== null && !headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }
    const hadToken = this.token !== null && this.token !== "";
    if (hadToken) {
      headers.set("Authorization", `Bearer ${this.token}`);
    }
    const response = await fetch(this.url(path), { ...init, headers, credentials: "omit" });
    if (response.status === 401 && hadToken) {
      this.token = null;
      await this.onSignedOut?.();
      throw new SignedOut();
    }
    if (!response.ok) {
      throw await problemFrom(response);
    }
    if (response.status === 204) {
      return { status: response.status, body: undefined as T };
    }
    const body = (await response.json()) as T;
    return { status: response.status, body };
  }

  async fetchJson<T>(path: string, init: RequestInit = {}): Promise<T> {
    const result = await this.fetchResponse<T>(path, init);
    return result.body;
  }

  get<T>(path: string): Promise<T> {
    return this.fetchJson<T>(path, { method: "GET" });
  }

  post<T>(path: string, payload?: unknown): Promise<T> {
    return this.fetchJson<T>(path, {
      method: "POST",
      body: payload === undefined ? null : JSON.stringify(payload),
    });
  }

  put<T>(path: string, payload: unknown): Promise<T> {
    return this.fetchJson<T>(path, { method: "PUT", body: JSON.stringify(payload) });
  }
}

/** Human-readable text for anything thrown around an API call. */
export function describeError(error: unknown): { code: string; detail: string } {
  if (error instanceof SignedOut) {
    return { code: "signed_out", detail: error.message };
  }
  if (error instanceof ApiError) {
    const fields = error.errors
      .map((e) => (e.field ? `${e.field}: ${e.message}` : e.message))
      .join("; ");
    return { code: error.code, detail: fields ? `${error.detail} (${fields})` : error.detail };
  }
  if (error instanceof TypeError) {
    return {
      code: "network_error",
      detail:
        "Could not reach the server. Check the address, your network and that the " +
        "certificate is trusted by this computer.",
    };
  }
  if (error instanceof Error) {
    return { code: "error", detail: error.message };
  }
  return { code: "error", detail: String(error) };
}
