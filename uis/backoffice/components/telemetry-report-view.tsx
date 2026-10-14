"use client";

import { useCallback, useEffect, useState } from "react";
import { readApiError } from "@/lib/api-client";
import { getTelemetryReport, type ReportWindow, type TelemetryReport } from "@/lib/telemetry-report";

/** Ventanas rápidas. «Por defecto» no envía fechas: el backend aplica sus 7 días y reutiliza su caché. */
const WINDOWS: Array<{ label: string; days: number | null }> = [
  { label: "Últimos 7 días (por defecto)", days: null },
  { label: "Últimas 24 h", days: 1 },
  { label: "Últimos 30 días", days: 30 },
];

function windowFor(days: number | null): ReportWindow {
  if (days === null) return {};
  const end = new Date();
  return { start: new Date(end.getTime() - days * 24 * 60 * 60 * 1000), end };
}

function formatInstant(iso: string): string {
  // "2026-10-05T12:15:46.009846Z" → "2026-10-05 12:15:46 UTC"
  return `${iso.replace("T", " ").replace(/(\.\d+)?Z$/, "")} UTC`;
}

function Section({ title, question, children }: { title: string; question: string; children: React.ReactNode }) {
  return (
    <section className="rounded-xl border border-zinc-200 bg-white p-4 sm:p-6">
      <h2 className="text-base font-black text-zinc-900">{title}</h2>
      <p className="mt-1 text-sm text-zinc-600">{question}</p>
      <div className="mt-4">{children}</div>
    </section>
  );
}

function Empty() {
  return <p className="text-sm text-zinc-500">Sin datos en este período.</p>;
}

/** Barra horizontal proporcional (sin librerías de gráficos). */
function Bar({ value, max, tone = "bg-red-800" }: { value: number; max: number; tone?: string }) {
  const width = max > 0 ? Math.max(2, Math.round((value / max) * 100)) : 0;
  return (
    <div className="h-3 w-full rounded bg-zinc-100" aria-hidden="true">
      <div className={`h-3 rounded ${tone}`} style={{ width: `${width}%` }} />
    </div>
  );
}

function Table({ head, rows }: { head: string[]; rows: Array<Array<string | number>> }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead className="border-b border-zinc-200 text-xs font-bold uppercase tracking-wide text-zinc-500">
          <tr>
            {head.map((label) => (
              <th key={label} className="px-3 py-2">{label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={index} className="border-b border-zinc-100 last:border-0">
              {row.map((cell, cellIndex) => (
                <td key={cellIndex} className="px-3 py-2 text-zinc-800">{cell}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function TelemetryReportView() {
  const [days, setDays] = useState<number | null>(null);
  const [report, setReport] = useState<TelemetryReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async (selectedDays: number | null) => {
    await Promise.resolve();
    setLoading(true);
    setError(null);
    try {
      const response = await getTelemetryReport(windowFor(selectedDays));
      if (!response.ok) {
        setError(await readApiError(response, "No se pudo cargar el reporte técnico."));
        return;
      }
      setReport((await response.json()) as TelemetryReport);
    } catch {
      setError("No se pudo conectar con el servidor.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void Promise.resolve().then(() => load(days));
  }, [load, days]);

  const metrics = report?.metrics;
  const maxPerDay = Math.max(0, ...(metrics?.events_per_day.map((row) => row.events) ?? []));
  const maxType = Math.max(0, ...(metrics?.event_type_distribution.map((row) => row.events) ?? []));

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Ventana de tiempo">
        {WINDOWS.map((option) => (
          <button
            key={option.label}
            type="button"
            onClick={() => setDays(option.days)}
            aria-pressed={days === option.days}
            className={`rounded-lg border px-3 py-2 text-xs font-bold ${
              days === option.days ? "border-red-800 bg-red-800 text-white" : "border-zinc-300 bg-white text-zinc-700 hover:border-red-800"
            }`}
          >
            {option.label}
          </button>
        ))}
      </div>

      {report && (
        <p className="rounded-lg border border-zinc-200 bg-white px-4 py-3 text-sm text-zinc-700" data-testid="report-period">
          <span className="font-bold">Período:</span> {formatInstant(report.period.from)} → {formatInstant(report.period.to)}
          <span className="text-zinc-500"> (inicio incluido, fin excluido, UTC)</span>
        </p>
      )}

      {loading && !report && <p className="rounded-lg border border-zinc-200 bg-white p-4 text-sm text-zinc-600">Cargando reporte...</p>}

      {error && (
        <div role="alert" className="rounded-xl border border-red-200 bg-red-50 p-6 text-sm text-red-800">
          <p className="font-semibold">{error}</p>
          <button type="button" onClick={() => void load(days)} className="mt-3 font-bold underline">Reintentar</button>
        </div>
      )}

      {metrics && (
        <>
          <Section title="Eventos por día" question="¿Cuánta telemetría llega cada día y desde qué lado (frontend, backend, job)?">
            {metrics.events_per_day.length === 0 ? <Empty /> : (
              <ul className="space-y-2">
                {metrics.events_per_day.map((row) => (
                  <li key={`${row.date}-${row.service}`} className="grid grid-cols-[9rem_1fr_3rem] items-center gap-3 text-sm">
                    <span className="text-zinc-700">{row.date} · {row.service}</span>
                    <Bar value={row.events} max={maxPerDay} />
                    <span className="text-right font-bold text-zinc-900">{row.events}</span>
                  </li>
                ))}
              </ul>
            )}
          </Section>

          <Section title="Tipos de evento dominantes" question="¿Qué tipos de evento concentran el tráfico?">
            {metrics.event_type_distribution.length === 0 ? <Empty /> : (
              <ul className="space-y-2">
                {metrics.event_type_distribution.map((row) => (
                  <li key={row.event_type} className="grid grid-cols-[14rem_1fr_6rem] items-center gap-3 text-sm">
                    <span className="truncate text-zinc-700">{row.event_type}</span>
                    <Bar value={row.events} max={maxType} tone="bg-zinc-700" />
                    <span className="text-right font-bold text-zinc-900">{row.events} · {row.share_pct}%</span>
                  </li>
                ))}
              </ul>
            )}
          </Section>

          <Section title="Tasa de errores por tipo" question="¿Qué errores técnicos ocurren cada día y qué parte del tráfico de ese día representan?">
            {metrics.error_rate_by_type.length === 0 ? <Empty /> : (
              <Table
                head={["Día", "Tipo de error", "Errores", "Eventos del día", "Tasa"]}
                rows={metrics.error_rate_by_type.map((row) => [row.date, row.event_type, row.errors, row.total_events, `${row.error_rate_pct}%`])}
              />
            )}
          </Section>

          <Section title="Latencia de la API por día y ruta" question="¿Qué tan rápido responde la API y en qué rutas es más lenta? (peticiones muestreadas)">
            {metrics.latency_by_day.length === 0 ? <Empty /> : (
              <Table
                head={["Día", "Ruta", "Muestras", "Media (ms)", "p95 (ms)", "Máx (ms)"]}
                rows={metrics.latency_by_day.map((row) => [row.date, row.routeTemplate, row.samples, row.mean_ms, row.p95_ms, row.max_ms])}
              />
            )}
          </Section>

          <Section title="Fallos de login por día" question="¿Qué proporción de los intentos de inicio de sesión falla cada día?">
            {metrics.auth_failure_rate.length === 0 ? <Empty /> : (
              <Table
                head={["Día", "Intentos", "Fallidos", "Tasa de fallo"]}
                rows={metrics.auth_failure_rate.map((row) => [row.date, row.attempts, row.failures, `${row.failure_rate_pct}%`])}
              />
            )}
          </Section>
        </>
      )}
    </div>
  );
}
