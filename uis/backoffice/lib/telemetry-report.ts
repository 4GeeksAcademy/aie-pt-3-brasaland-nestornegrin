import { apiFetch } from "@/lib/api-client";

/** Respuesta de `GET /telemetry/report` (métricas técnicas/operacionales, no de negocio). */
export type TelemetryReport = {
  period: { from: string; to: string };
  metrics: {
    events_per_day: Array<{ date: string; service: string; events: number }>;
    event_type_distribution: Array<{ event_type: string; events: number; share_pct: number }>;
    error_rate_by_type: Array<{ date: string; event_type: string; errors: number; total_events: number; error_rate_pct: number }>;
    latency_by_day: Array<{ date: string; routeTemplate: string; samples: number; mean_ms: number; p95_ms: number; max_ms: number }>;
    auth_failure_rate: Array<{ date: string; attempts: number; failures: number; failure_rate_pct: number }>;
  };
};

/** Ventana pedida al backend. Sin fechas, el backend usa los últimos 7 días (UTC). */
export type ReportWindow = { start?: Date; end?: Date };

export async function getTelemetryReport(window: ReportWindow = {}): Promise<Response> {
  const params = new URLSearchParams();
  if (window.start) params.set("start_date", window.start.toISOString());
  if (window.end) params.set("end_date", window.end.toISOString());
  const query = params.toString();
  return apiFetch(`/telemetry/report${query ? `?${query}` : ""}`);
}
