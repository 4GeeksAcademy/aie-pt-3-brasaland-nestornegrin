// Cliente del endpoint de la base de conocimiento (Hito 7 — RAG): POST /knowledge/query.
// Ningún componente llama a fetch directamente: pasan por askKnowledge().
//
// La API responde { "answer": "..." } con el texto que redacta el modelo; nunca chunks ni puntuaciones.

import { apiFetch, readApiError } from "./api-client";

export const MAX_QUESTION_LENGTH = 1000;

export class KnowledgeQueryError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "KnowledgeQueryError";
  }
}

export async function askKnowledge(question: string): Promise<string> {
  const trimmed = question.trim();
  if (!trimmed) throw new KnowledgeQueryError("Escribe una pregunta para consultar la base de conocimiento.");
  if (trimmed.length > MAX_QUESTION_LENGTH) {
    throw new KnowledgeQueryError(`La pregunta es demasiado larga (máximo ${MAX_QUESTION_LENGTH} caracteres).`);
  }

  let response: Response;
  try {
    // authenticated = false: el endpoint del RAG no usa el token de sesión.
    response = await apiFetch(
      "/knowledge/query",
      { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question: trimmed }) },
      false,
    );
  } catch {
    throw new KnowledgeQueryError("No se pudo conectar con el servidor. Comprueba tu conexión e inténtalo de nuevo.");
  }

  if (!response.ok) {
    throw new KnowledgeQueryError(
      await readApiError(response, "El asistente no pudo responder en este momento. Inténtalo de nuevo en unos minutos."),
    );
  }

  let payload: { answer?: unknown };
  try {
    payload = (await response.json()) as { answer?: unknown };
  } catch {
    throw new KnowledgeQueryError("El servidor respondió con un formato inesperado.");
  }
  // Una respuesta sin texto es un fallo, no una respuesta vacía que parezca válida.
  if (typeof payload.answer !== "string" || !payload.answer.trim()) {
    throw new KnowledgeQueryError("El asistente devolvió una respuesta vacía. Inténtalo de nuevo.");
  }
  return payload.answer;
}
