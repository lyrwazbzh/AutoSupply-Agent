export interface AuthUser {
  subject: string;
  username: string;
  displayName?: string;
  roles: string[];
  permissions: string[];
}

interface TokenPayload {
  accessToken: string;
  expiresAt: number;
  user: AuthUser;
}

interface Envelope<T> {
  code: number;
  message: string;
  data: T;
}

let accessToken = "";
let refreshInFlight: Promise<TokenPayload> | null = null;
const sessionListeners = new Set<(user: AuthUser | null) => void>();

function applyToken(payload: TokenPayload): TokenPayload {
  accessToken = payload.accessToken;
  sessionListeners.forEach((listener) => listener(payload.user));
  return payload;
}

async function readEnvelope<T>(response: Response): Promise<T> {
  const body = (await response.json().catch(() => null)) as Envelope<T> | null;
  if (!response.ok || !body || body.code !== 200) {
    throw new Error(body?.message || `请求失败 (${response.status})`);
  }
  return body.data;
}

export async function login(username: string, password: string): Promise<TokenPayload> {
  const response = await fetch("/api/auth/login", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  return applyToken(await readEnvelope<TokenPayload>(response));
}

export async function refreshSession(): Promise<TokenPayload> {
  if (!refreshInFlight) {
    refreshInFlight = fetch("/api/auth/refresh", {
      method: "POST",
      credentials: "include",
    })
      .then((response) => readEnvelope<TokenPayload>(response))
      .then(applyToken)
      .finally(() => {
        refreshInFlight = null;
      });
  }
  return refreshInFlight;
}

export async function logout(): Promise<void> {
  const token = accessToken;
  accessToken = "";
  await fetch("/api/auth/logout", {
    method: "POST",
    credentials: "include",
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  }).catch(() => undefined);
}

export function clearAccessToken(): void {
  accessToken = "";
  sessionListeners.forEach((listener) => listener(null));
}

export function subscribeSession(listener: (user: AuthUser | null) => void): () => void {
  sessionListeners.add(listener);
  return () => sessionListeners.delete(listener);
}

export async function authFetch(
  input: RequestInfo | URL,
  init: RequestInit = {},
  retry = true
): Promise<Response> {
  const headers = new Headers(init.headers);
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
  let response = await fetch(input, { ...init, headers, credentials: "include" });
  if (response.status !== 401 || !retry || String(input).startsWith("/api/auth/")) {
    return response;
  }
  try {
    await refreshSession();
  } catch {
    clearAccessToken();
    return response;
  }
  const retriedHeaders = new Headers(init.headers);
  retriedHeaders.set("Authorization", `Bearer ${accessToken}`);
  response = await fetch(input, {
    ...init,
    headers: retriedHeaders,
    credentials: "include",
  });
  return response;
}

export async function erpJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const response = await authFetch(`/api/erp${path}`, { ...init, headers });
  return readEnvelope<T>(response);
}
