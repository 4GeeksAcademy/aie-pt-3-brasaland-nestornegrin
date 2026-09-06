const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
export const ACCESS_TOKEN_KEY = "brasaland_access_token";
export const AUTH_CHANGE_EVENT = "brasaland-auth-change";

export function getAccessToken(): string | null {
  return typeof window === "undefined" ? null : window.localStorage.getItem(ACCESS_TOKEN_KEY);
}

export function saveAccessToken(token: string): void {
  window.localStorage.setItem(ACCESS_TOKEN_KEY, token);
  window.dispatchEvent(new Event(AUTH_CHANGE_EVENT));
}

export function clearAccessToken(): void {
  window.localStorage.removeItem(ACCESS_TOKEN_KEY);
  window.dispatchEvent(new Event(AUTH_CHANGE_EVENT));
}

function redirectToLogin(): void {
  clearAccessToken();
  if (window.location.pathname !== "/login") window.location.assign("/login");
}

export async function apiFetch(path: string, init: RequestInit = {}, authenticated = true): Promise<Response> {
  const headers = new Headers(init.headers);
  if (authenticated) {
    const token = getAccessToken();
    if (token) headers.set("Authorization", `Bearer ${token}`);
  }

  const response = await fetch(`${API_URL}${path}`, { ...init, headers });
  if (authenticated && response.status === 401) redirectToLogin();
  return response;
}

export async function readApiError(response: Response, fallback: string): Promise<string> {
  return (await readApiErrorDetails(response, fallback)).message;
}

export async function readApiErrorDetails(response: Response, fallback: string): Promise<{ message: string; fields: Record<string, string> }> {
  const fields: Record<string, string> = {};
  try {
    const payload = (await response.json()) as { detail?: string | Array<{ msg?: string }> };
    if (typeof payload.detail === "string") return { message: payload.detail, fields };
    if (Array.isArray(payload.detail)) {
      for (const item of payload.detail) {
        const detail = item as { msg?: string; loc?: Array<string | number> };
        const field = detail.loc?.at(-1);
        if (typeof field === "string") fields[field] = detail.msg ?? "Dato inválido";
      }
      return { message: Object.values(fields).join(". ") || fallback, fields };
    }
  } catch {
    // La API puede responder sin JSON cuando hay un error de red o de proxy.
  }
  return { message: fallback, fields };
}

export { API_URL };