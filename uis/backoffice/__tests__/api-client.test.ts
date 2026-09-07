import {
  apiFetch,
  clearAccessToken,
  getAccessToken,
  readApiErrorDetails,
  saveAccessToken,
} from "../lib/api-client";

function makeJsonResponse(body: unknown): Response {
  return { json: async () => body } as Response;
}

beforeEach(() => {
  window.localStorage.clear();
  jest.restoreAllMocks();
});

describe("getAccessToken / saveAccessToken / clearAccessToken", () => {
  test("camino feliz: guardar y luego leer devuelve el mismo token", () => {
    saveAccessToken("abc.def.ghi");
    expect(getAccessToken()).toBe("abc.def.ghi");
  });

  test("caso límite: no hay ningún token guardado todavía", () => {
    expect(getAccessToken()).toBeNull();
  });

  test("modo de fallo: clearAccessToken elimina un token existente", () => {
    saveAccessToken("abc.def.ghi");
    clearAccessToken();
    expect(getAccessToken()).toBeNull();
  });
});

describe("readApiErrorDetails", () => {
  test("camino feliz: detail como string simple", async () => {
    const result = await readApiErrorDetails(makeJsonResponse({ detail: "Algo salió mal" }), "fallback");
    expect(result.message).toBe("Algo salió mal");
    expect(result.fields).toEqual({});
  });

  test("caso límite: detail en el formato real de FastAPI (lista de {loc, msg}) identifica el campo", async () => {
    const body = { detail: [{ loc: ["body", "email"], msg: "value is not a valid email address" }] };
    const result = await readApiErrorDetails(makeJsonResponse(body), "fallback");
    expect(result.fields.email).toBe("value is not a valid email address");
  });

  test("modo de fallo: un cuerpo que no se puede parsear cae al mensaje por defecto", async () => {
    const brokenResponse = { json: async () => { throw new Error("cuerpo no es JSON"); } } as unknown as Response;
    const result = await readApiErrorDetails(brokenResponse, "Mensaje por defecto");
    expect(result.message).toBe("Mensaje por defecto");
    expect(result.fields).toEqual({});
  });
});

describe("apiFetch", () => {
  test("camino feliz: adjunta el header Authorization cuando hay token y authenticated=true", async () => {
    saveAccessToken("mi-token");
    const fetchMock = jest.fn().mockResolvedValue({ status: 200 } as Response);
    global.fetch = fetchMock as unknown as typeof fetch;

    await apiFetch("/algo");

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect((init.headers as Headers).get("Authorization")).toBe("Bearer mi-token");
  });

  test("caso límite: sin token guardado, no se adjunta ningún header Authorization", async () => {
    const fetchMock = jest.fn().mockResolvedValue({ status: 200 } as Response);
    global.fetch = fetchMock as unknown as typeof fetch;

    await apiFetch("/algo");

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect((init.headers as Headers).has("Authorization")).toBe(false);
  });

  test("modo de fallo: una respuesta 401 limpia el token y redirige a /login", async () => {
    saveAccessToken("mi-token");
    global.fetch = jest.fn().mockResolvedValue({ status: 401 } as Response) as unknown as typeof fetch;
    const assignMock = jest.fn();
    // jsdom no permite reasignar window.location.assign directamente; hay que
    // borrar la propiedad y reemplazarla por un objeto simulado.
    delete (window as unknown as { location?: unknown }).location;
    (window as unknown as { location: Location }).location = { assign: assignMock, pathname: "/incidents" } as unknown as Location;

    await apiFetch("/algo");

    expect(getAccessToken()).toBeNull();
    expect(assignMock).toHaveBeenCalledWith("/login");
  });
});
