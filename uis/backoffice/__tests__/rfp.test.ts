import { isLive, MAX_PDF_BYTES, reprocessTicket, statusLabel, uploadRfp, validatePdf } from "../lib/rfp";

const pdf = (name: string, size = 10) => new File([new Uint8Array(size)], name, { type: "application/pdf" });

describe("validatePdf", () => {
  test("acepta un PDF y rechaza vacío, grande o de otro tipo", () => {
    expect(validatePdf(pdf("rfp.pdf"))).toBeNull();
    expect(validatePdf(null)).toMatch(/Selecciona/);
    expect(validatePdf(pdf("rfp.txt"))).toMatch(/PDF/);
    expect(validatePdf(new File([], "rfp.pdf"))).toMatch(/vacío/);
    expect(validatePdf({ name: "a.pdf", size: MAX_PDF_BYTES + 1 } as File)).toMatch(/10 MB/);
  });
});

describe("estado del ticket", () => {
  test("solo hace polling mientras el pipeline corre", () => {
    expect(isLive({ status: "analizando", processing: "running" })).toBe(true);
    expect(isLive({ status: "analizando", processing: "failed" })).toBe(false);
    expect(isLive({ status: "analizando", processing: "stalled" })).toBe(false);
    expect(isLive({ status: "descartado", processing: "idle" })).toBe(false);
  });
  test("etiquetas claras para cada caso", () => {
    expect(statusLabel({ status: "analisis_completo", processing: "idle" })).toBe("Análisis completo");
    expect(statusLabel({ status: "descartado", processing: "idle" })).toBe("Descartado");
    expect(statusLabel({ status: "analizando", processing: "failed" })).toMatch(/Falló/);
    expect(statusLabel({ status: "analizando", processing: "stalled" })).toMatch(/Detenido/);
  });
});

describe("llamadas a la API", () => {
  beforeEach(() => window.localStorage.clear());
  test("uploadRfp envía multipart sin Content-Type manual y devuelve el ticket", async () => {
    const fetchMock = jest.fn(async () => ({ ok: true, status: 202, json: async () => ({ ticket_id: 7, status: "analizando" }) }));
    global.fetch = fetchMock as unknown as typeof fetch;
    await expect(uploadRfp(pdf("rfp.pdf"))).resolves.toEqual({ ticket_id: 7, status: "analizando" });
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toMatch(/\/rfp\/tickets$/);
    expect(init.body).toBeInstanceOf(FormData);
    expect(new Headers(init.headers).has("Content-Type")).toBe(false);
  });
  test("propaga el mensaje de error del backend", async () => {
    global.fetch = jest.fn(async () => ({ ok: false, status: 415, json: async () => ({ detail: "El archivo no es un PDF válido." }) })) as unknown as typeof fetch;
    await expect(uploadRfp(pdf("x.pdf"))).rejects.toThrow("El archivo no es un PDF válido.");
  });
  test("reprocessTicket usa ?force=true solo cuando se pide", async () => {
    const fetchMock = jest.fn(async () => ({ ok: true, status: 202, json: async () => ({}) }));
    global.fetch = fetchMock as unknown as typeof fetch;
    await reprocessTicket(3); await reprocessTicket(3, true);
    expect((fetchMock.mock.calls[0] as unknown as [string])[0]).toMatch(/\/rfp\/tickets\/3\/reprocess$/);
    expect((fetchMock.mock.calls[1] as unknown as [string])[0]).toMatch(/reprocess\?force=true$/);
  });
});
