import type {
  ChatMessageCreate,
  ChatMessageOut,
  ChatThreadOut,
  JobOut,
  LLMKeyCreate,
  LLMKeyOut,
  PreferencesBody,
  PreferencesOut,
  RenderJsonBody,
  TokenResponse,
  UserOut,
} from "./types";

const TOKEN_KEY = "pdf_pipeline_access_token";

export function getApiBase(): string {
  const v = import.meta.env.VITE_API_BASE_URL;
  if (v === undefined || v === "") return "";
  return v.replace(/\/$/, "");
}

export function getStoredToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setStoredToken(token: string | null): void {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

type ApiFetchOptions = RequestInit & {
  skipAuth?: boolean;
};

async function parseJsonError(res: Response): Promise<string> {
  try {
    const data = (await res.json()) as { detail?: unknown };
    if (typeof data.detail === "string") return data.detail;
    if (Array.isArray(data.detail)) return JSON.stringify(data.detail);
    return res.statusText || "Request failed";
  } catch {
    return res.statusText || "Request failed";
  }
}

export async function apiFetch(
  path: string,
  options: ApiFetchOptions = {},
): Promise<Response> {
  const { skipAuth, headers: initHeaders, ...rest } = options;
  const headers = new Headers(initHeaders);
  if (!skipAuth) {
    const t = getStoredToken();
    if (t) headers.set("Authorization", `Bearer ${t}`);
  }
  const url = `${getApiBase()}${path.startsWith("/") ? path : `/${path}`}`;
  return fetch(url, { ...rest, headers });
}

export async function apiJson<T>(
  path: string,
  options: ApiFetchOptions = {},
): Promise<T> {
  const res = await apiFetch(path, options);
  if (res.status === 401) {
    setStoredToken(null);
    throw new Error("Unauthorized");
  }
  if (!res.ok) throw new Error(await parseJsonError(res));
  return res.json() as Promise<T>;
}

// --- Auth ---

export async function registerUser(body: {
  email: string;
  password: string;
}): Promise<UserOut> {
  return apiJson<UserOut>("/v1/auth/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    skipAuth: true,
  });
}

export async function loginUser(body: {
  email: string;
  password: string;
}): Promise<TokenResponse> {
  return apiJson<TokenResponse>("/v1/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    skipAuth: true,
  });
}

export async function fetchMe(): Promise<UserOut> {
  return apiJson<UserOut>("/v1/me");
}

// --- Preferences ---

export async function getPreferences(): Promise<PreferencesOut> {
  return apiJson<PreferencesOut>("/v1/me/preferences");
}

export async function putPreferences(
  body: PreferencesBody,
): Promise<PreferencesOut> {
  return apiJson<PreferencesOut>("/v1/me/preferences", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

// --- Keys ---

export async function listKeys(): Promise<LLMKeyOut[]> {
  return apiJson<LLMKeyOut[]>("/v1/me/keys");
}

export async function createKey(body: LLMKeyCreate): Promise<LLMKeyOut> {
  return apiJson<LLMKeyOut>("/v1/me/keys", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function deleteKey(keyId: string): Promise<void> {
  const res = await apiFetch(`/v1/me/keys/${encodeURIComponent(keyId)}`, {
    method: "DELETE",
  });
  if (res.status === 401) {
    setStoredToken(null);
    throw new Error("Unauthorized");
  }
  if (!res.ok) throw new Error(await parseJsonError(res));
}

// --- Jobs ---

export async function listJobs(limit = 50): Promise<JobOut[]> {
  return apiJson<JobOut[]>(`/v1/jobs?limit=${limit}`);
}

export async function getJob(jobId: string): Promise<JobOut> {
  return apiJson<JobOut>(`/v1/jobs/${encodeURIComponent(jobId)}`);
}

/** Returns blob and Content-Type from success; throws with message on error JSON. */
export async function renderJson(body: RenderJsonBody): Promise<{
  blob: Blob;
  contentType: string | null;
  filename: string | null;
}> {
  const res = await apiFetch("/v1/jobs/render-json", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (res.status === 401) {
    setStoredToken(null);
    throw new Error("Unauthorized");
  }
  if (!res.ok) throw new Error(await parseJsonError(res));
  const cd = res.headers.get("Content-Disposition");
  let filename: string | null = null;
  if (cd) {
    const m = /filename\*?=(?:UTF-8''|")?([^";\n]+)/i.exec(cd);
    if (m) filename = decodeURIComponent(m[1].replace(/"/g, ""));
  }
  const blob = await res.blob();
  return {
    blob,
    contentType: res.headers.get("Content-Type"),
    filename,
  };
}

export async function renderFile(params: {
  file?: File | null;
  text?: string | null;
  options?: Record<string, unknown> | null;
}): Promise<{
  blob: Blob;
  contentType: string | null;
  filename: string | null;
}> {
  const fd = new FormData();
  if (params.file) fd.append("file", params.file);
  if (params.text != null && params.text !== "")
    fd.append("text", params.text);
  if (params.options && Object.keys(params.options).length > 0) {
    fd.append("options", JSON.stringify(params.options));
  }
  const res = await apiFetch("/v1/jobs/render-file", {
    method: "POST",
    body: fd,
  });
  if (res.status === 401) {
    setStoredToken(null);
    throw new Error("Unauthorized");
  }
  if (!res.ok) throw new Error(await parseJsonError(res));
  const cd = res.headers.get("Content-Disposition");
  let filename: string | null = null;
  if (cd) {
    const m = /filename\*?=(?:UTF-8''|")?([^";\n]+)/i.exec(cd);
    if (m) filename = decodeURIComponent(m[1].replace(/"/g, ""));
  }
  const blob = await res.blob();
  return {
    blob,
    contentType: res.headers.get("Content-Type"),
    filename,
  };
}

export async function downloadJob(jobId: string): Promise<{
  blob: Blob;
  contentType: string | null;
  filename: string | null;
}> {
  const res = await apiFetch(
    `/v1/jobs/${encodeURIComponent(jobId)}/download`,
    { method: "GET" },
  );
  if (res.status === 401) {
    setStoredToken(null);
    throw new Error("Unauthorized");
  }
  if (!res.ok) throw new Error(await parseJsonError(res));
  const cd = res.headers.get("Content-Disposition");
  let filename: string | null = null;
  if (cd) {
    const m = /filename\*?=(?:UTF-8''|")?([^";\n]+)/i.exec(cd);
    if (m) filename = decodeURIComponent(m[1].replace(/"/g, ""));
  }
  const blob = await res.blob();
  return {
    blob,
    contentType: res.headers.get("Content-Type"),
    filename,
  };
}

// --- Chat ---

export async function listThreads(): Promise<ChatThreadOut[]> {
  return apiJson<ChatThreadOut[]>("/v1/chat/threads");
}

export async function createThread(title: string): Promise<ChatThreadOut> {
  return apiJson<ChatThreadOut>("/v1/chat/threads", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });
}

export async function listMessages(
  threadId: string,
): Promise<ChatMessageOut[]> {
  return apiJson<ChatMessageOut[]>(
    `/v1/chat/threads/${encodeURIComponent(threadId)}/messages`,
  );
}

export async function postMessage(
  threadId: string,
  body: ChatMessageCreate,
): Promise<ChatMessageOut> {
  return apiJson<ChatMessageOut>(
    `/v1/chat/threads/${encodeURIComponent(threadId)}/messages`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
}
