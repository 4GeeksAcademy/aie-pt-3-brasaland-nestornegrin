/**
 * Errores no controlados del frontend → frontend_error_captured.
 * Privacidad: nunca se envía el mensaje del error (puede contener datos del
 * usuario); solo nombre, huella estable y el primer frame sin dominio ni query.
 */
import { track } from "@/services/telemetry";
import { routeTemplate } from "@/services/telemetry-http";

export type ErrorSource = "error_boundary" | "window_error" | "unhandled_rejection";

/** Hash FNV-1a doble de 32 bits → 16 hex. No criptográfico: solo agrupa errores iguales. */
export function fingerprint(text: string): string {
  let h1 = 0x811c9dc5;
  let h2 = 0x01000193;
  for (let i = 0; i < text.length; i += 1) {
    const c = text.charCodeAt(i);
    h1 = Math.imul(h1 ^ c, 0x01000193) >>> 0;
    h2 = Math.imul(h2 ^ c, 0x85ebca6b) >>> 0;
  }
  return h1.toString(16).padStart(8, "0") + h2.toString(16).padStart(8, "0");
}

export function topFrameOf(stack: string | undefined): string | undefined {
  if (!stack) return undefined;
  for (const line of stack.split("\n").slice(1)) {
    const match = line.match(/(?:https?:\/\/[^/\s)]+)?(\/[^\s):?#]+)(?:\?[^\s:)]*)?:(\d+):\d+\)?\s*$/);
    if (match) {
      const frame = `${match[1].replace(/[^A-Za-z0-9_./-]/g, "_")}:${match[2]}`;
      return frame.slice(0, 128);
    }
  }
  return undefined;
}

function nameOf(error: unknown): string {
  const raw = error instanceof Error ? error.name : typeof error === "object" && error !== null ? "Object" : typeof error;
  const clean = raw.replace(/[^A-Za-z0-9_]/g, "_").slice(0, 64);
  return /^[A-Za-z_]/.test(clean) ? clean : "Error";
}

export function captureError(source: ErrorSource, error: unknown): void {
  const stack = error instanceof Error ? error.stack : undefined;
  const topFrame = topFrameOf(stack);
  const name = nameOf(error);
  track("frontend_error_captured", {
    errorSource: source,
    errorName: name,
    fingerprint: fingerprint(`${name}|${topFrame ?? ""}`),
    routeTemplate: routeTemplate(typeof window === "undefined" ? "/" : window.location.pathname),
    ...(topFrame ? { topFrame } : {}),
  });
}

/** Registra window.onerror y unhandledrejection. Devuelve la función de limpieza. */
export function installGlobalErrorHandlers(): () => void {
  const onError = (event: ErrorEvent) => captureError("window_error", event.error ?? new Error("window_error"));
  const onRejection = (event: PromiseRejectionEvent) => captureError("unhandled_rejection", event.reason);
  window.addEventListener("error", onError);
  window.addEventListener("unhandledrejection", onRejection);
  return () => {
    window.removeEventListener("error", onError);
    window.removeEventListener("unhandledrejection", onRejection);
  };
}
