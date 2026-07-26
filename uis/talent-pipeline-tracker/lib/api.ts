import { RecordCreate, RecordPatch, RecordsResponse, Note, NoteCreate, RecordOut } from "@/types";

const baseUrl = process.env.NEXT_PUBLIC_API_URL ?? "https://playground.4geeks.com/tracker/api/v1";

async function fetchJson<T>(input: RequestInfo, init?: RequestInit): Promise<T> {
  const response = await fetch(input, init);
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || response.statusText);
  }
  return response.json();
}

export async function getRecords(params?: { status?: string; stage?: string; search?: string }): Promise<RecordsResponse> {
  const url = new URL(`${baseUrl}/records`);
  if (params?.status) url.searchParams.set("status", params.status);
  if (params?.stage) url.searchParams.set("stage", params.stage);
  if (params?.search) url.searchParams.set("search", params.search);
  url.searchParams.set("limit", "200");
  return fetchJson<RecordsResponse>(url.toString());
}

export async function getRecord(id: string): Promise<RecordOut> {
  return fetchJson<RecordOut>(`${baseUrl}/records/${id}`);
}

export async function getNotes(id: string): Promise<Note[]> {
  return fetchJson<Note[]>(`${baseUrl}/records/${id}/notes`);
}

export async function createRecord(payload: RecordCreate): Promise<RecordOut> {
  return fetchJson<RecordOut>(`${baseUrl}/records`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function updateRecord(id: string, payload: RecordCreate): Promise<RecordOut> {
  return fetchJson<RecordOut>(`${baseUrl}/records/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function patchRecord(id: string, payload: RecordPatch): Promise<RecordOut> {
  return fetchJson<RecordOut>(`${baseUrl}/records/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function createNote(id: string, payload: NoteCreate): Promise<Note> {
  return fetchJson<Note>(`${baseUrl}/records/${id}/notes`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export async function deleteNote(id: string, noteId: string): Promise<void> {
  const response = await fetch(`${baseUrl}/records/${id}/notes/${noteId}`, {
    method: "DELETE",
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || response.statusText);
  }
}
