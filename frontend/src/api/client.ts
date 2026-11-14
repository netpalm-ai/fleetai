export const API_BASE = "/api/v1";

export class ApiError extends Error {
  status: number;

  constructor(path: string, status: number, detail: string) {
    super(detail || path + " " + String(status));
    this.status = status;
  }
}

function url(path: string): string {
  if (path.startsWith("http") || path.startsWith(API_BASE)) {
    return path;
  }
  return API_BASE + (path.startsWith("/") ? path : "/" + path);
}

export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const method = (init.method ?? "GET").toUpperCase();
  const headers = new Headers(init.headers);
  if (method !== "GET" && method !== "HEAD" && !headers.has("X-Requested-With")) {
    headers.set("X-Requested-With", "fleetai");
  }
  if (init.body != null && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const href = url(path);
  const response = await fetch(href, {
    ...init,
    method,
    headers,
    credentials: "same-origin",
  });
  if (response.status === 204) {
    return undefined as T;
  }
  const text = await response.text();
  let body: unknown = null;
  if (text) {
    try {
      body = JSON.parse(text) as unknown;
    } catch {
      body = text;
    }
  }
  if (!response.ok) {
    let detail = href + " " + String(response.status);
    if (typeof body === "object" && body !== null && "detail" in body) {
      const value = (body as { detail: unknown }).detail;
      if (typeof value === "string") {
        detail = value;
      }
    }
    throw new ApiError(href, response.status, detail);
  }
  return body as T;
}

export async function getJson<T>(path: string): Promise<T> {
  return request<T>(path);
}
