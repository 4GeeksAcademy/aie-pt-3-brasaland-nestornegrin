import { askKnowledge, KnowledgeQueryError, MAX_QUESTION_LENGTH } from "../lib/knowledge";

function mockFetch(response: Partial<Response> | Error) {
  const fetchMock = jest.fn(async () => {
    if (response instanceof Error) throw response;
    return response as Response;
  });
  global.fetch = fetchMock as unknown as typeof fetch;
  return fetchMock;
}

function jsonResponse(body: unknown, init: { ok?: boolean; status?: number } = {}): Partial<Response> {
  return { ok: init.ok ?? true, status: init.status ?? 200, json: async () => body };
}

beforeEach(() => {
  window.localStorage.clear();
  jest.restoreAllMocks();
});

describe("askKnowledge", () => {
  test("camino feliz: envía la pregunta recortada y devuelve solo el texto de answer", async () => {
    const fetchMock = mockFetch(jsonResponse({ answer: "Necesitas 50 puntos." }));
    await expect(askKnowledge("  ¿Cuántos puntos para Oro?  ")).resolves.toBe("Necesitas 50 puntos.");

    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toMatch(/\/knowledge\/query$/);
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({ question: "¿Cuántos puntos para Oro?" });
    expect(new Headers(init.headers).has("Authorization")).toBe(false); // el endpoint no usa sesión
  });

  test("caso límite: pregunta vacía o solo espacios no llama a la API", async () => {
    const fetchMock = mockFetch(jsonResponse({ answer: "x" }));
    await expect(askKnowledge("   ")).rejects.toThrow(KnowledgeQueryError);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  test("caso límite: pregunta demasiado larga se rechaza antes de llamar a la API", async () => {
    const fetchMock = mockFetch(jsonResponse({ answer: "x" }));
    await expect(askKnowledge("a".repeat(MAX_QUESTION_LENGTH + 1))).rejects.toThrow(/demasiado larga/);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  test("modo de fallo: error HTTP muestra el mensaje de la API, no una respuesta vacía", async () => {
    mockFetch(jsonResponse({ detail: "El asistente no pudo responder en este momento." }, { ok: false, status: 502 }));
    await expect(askKnowledge("hola")).rejects.toThrow("El asistente no pudo responder en este momento.");
  });

  test("modo de fallo: sin conexión lanza un error claro", async () => {
    mockFetch(new TypeError("Failed to fetch"));
    await expect(askKnowledge("hola")).rejects.toThrow(/No se pudo conectar/);
  });

  test("modo de fallo: una respuesta sin texto se trata como error", async () => {
    mockFetch(jsonResponse({ answer: "   " }));
    await expect(askKnowledge("hola")).rejects.toThrow(/respuesta vacía/);
    mockFetch(jsonResponse({}));
    await expect(askKnowledge("hola")).rejects.toThrow(/respuesta vacía/);
  });
});
