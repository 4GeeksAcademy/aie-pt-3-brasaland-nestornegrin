"use client";

import { useCallback, useEffect, useState } from "react";
import { ACTOR_LABELS, STATUS_LABELS, canReview, figureWarning, financialCloseApi, rejectionError, sortReports, sourceLabel, type AuditEvent, type Figure, type Report, type ReportSummary } from "@/lib/financial-close";

const card = "rounded-2xl border border-zinc-200 bg-white p-6 text-zinc-900 shadow-sm dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100";
const button = "rounded-lg bg-red-800 px-4 py-2 text-sm font-bold text-white hover:bg-red-900 focus:outline-none focus:ring-2 focus:ring-red-800/40 disabled:cursor-not-allowed disabled:opacity-60";
const outline = "rounded-lg border border-zinc-300 px-4 py-2 text-sm font-semibold hover:bg-zinc-100 dark:border-zinc-600 dark:hover:bg-zinc-800";
const msg = (e: unknown) => (e instanceof Error ? e.message : "Error inesperado.");

export function FinancialClosePanel() {
  const [reports, setReports] = useState<ReportSummary[]>([]);
  const [current, setCurrent] = useState<Report | null>(null);
  const [figureId, setFigureId] = useState("");
  const [figure, setFigure] = useState<Figure | null>(null);
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [comment, setComment] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try { setReports(sortReports(await financialCloseApi.reports())); setError(""); } catch (e) { setError(msg(e)); }
  }, []);
  useEffect(() => { void Promise.resolve().then(() => load()); }, [load]);

  const run = async (fn: () => Promise<void>) => { setBusy(true); try { await fn(); setError(""); } catch (e) { setError(msg(e)); } finally { setBusy(false); } };
  const open = (id: number) => run(async () => { setCurrent(await financialCloseApi.report(id)); setFigure(null); setComment(""); });
  const decide = (decision: "approve" | "reject") => {
    if (!current) return;
    if (decision === "reject") { const problem = rejectionError(comment); if (problem) { setError(problem); return; } }
    void run(async () => { const next = await financialCloseApi.review(current.id, decision, comment); await load(); setCurrent(next); setComment(""); });
  };
  const trace = () => run(async () => { if (current && figureId.trim()) setFigure(await financialCloseApi.figure(current.id, figureId.trim())); });

  return (
    <div className="mx-auto grid max-w-5xl gap-4 p-4">
      <h1 className="text-2xl font-bold">Cierre financiero mensual</h1>
      <p className="text-sm">Un agente prepara el cierre con herramientas de cálculo deterministas; cada cifra enlaza a los registros que la producen. <strong>Nada se distribuye hasta que Felipe Guerrero lo aprueba.</strong> Lo que falta se declara.</p>
      {error && <p role="alert" className={card}>{error}</p>}
      <div className="flex flex-wrap gap-2">
        <button className={outline} disabled={busy} onClick={() => run(async () => { setCurrent(await financialCloseApi.demo()); await load(); })}>Generar cierre de ejemplo</button>
        <button className={outline} disabled={busy} onClick={() => run(async () => setEvents(await financialCloseApi.events()))}>Ver registro de acciones</button>
      </div>

      <section className={card} aria-label="Informes">
        {reports.length === 0 && <p>No hay informes visibles para ti. Los pendientes solo los ve el revisor; los aprobados, los destinatarios.</p>}
        <ul className="grid gap-2">
          {reports.map((r) => (
            <li key={r.id} className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-zinc-50 px-3 py-2 text-sm dark:bg-zinc-800">
              <span><strong>{r.period}</strong> · v{r.version} · {STATUS_LABELS[r.status]}</span>
              <button className={outline} onClick={() => open(r.id)}>Abrir</button>
            </li>
          ))}
        </ul>
      </section>

      {current && (
        <section className={card} aria-label="Informe">
          <h2 className="text-lg font-bold">{current.period} · versión {current.version} · {STATUS_LABELS[current.status]}</h2>
          <ul className="mt-2 text-sm">{current.content.summary.map((l) => <li key={l}>• {l}</li>)}</ul>
          {canReview(current) && (
            <div className="mt-4 grid gap-2">
              <label className="text-sm font-semibold" htmlFor="comment">Comentarios (obligatorios para rechazar)</label>
              <textarea id="comment" rows={3} className="rounded-lg border border-zinc-300 p-2 text-sm dark:border-zinc-600 dark:bg-zinc-800" value={comment} onChange={(e) => setComment(e.target.value)} />
              <div className="flex gap-2">
                <button className={button} disabled={busy} onClick={() => decide("approve")}>Aprobar y distribuir</button>
                <button className={outline} disabled={busy} onClick={() => decide("reject")}>Rechazar con comentarios</button>
              </div>
            </div>
          )}
          {current.reviews.length > 0 && <ul className="mt-3 text-sm">{current.reviews.map((r) => <li key={r.id}>{r.decision === "approve" ? "Aprobado" : "Rechazado"} por {r.staff_id}: {r.comment || "—"}</li>)}</ul>}
          <details className="mt-4"><summary className="cursor-pointer text-sm font-semibold">Informe completo (Markdown)</summary><pre className="mt-2 overflow-x-auto whitespace-pre-wrap text-xs">{current.markdown}</pre></details>
          <div className="mt-4 flex flex-wrap items-end gap-2">
            <label className="text-sm font-semibold" htmlFor="figure">Origen de una cifra (p. ej. FL.MKT.ACT)</label>
            <input id="figure" className="rounded-lg border border-zinc-300 p-2 text-sm dark:border-zinc-600 dark:bg-zinc-800" value={figureId} onChange={(e) => setFigureId(e.target.value)} />
            <button className={outline} disabled={busy || !figureId.trim()} onClick={trace}>Ver origen</button>
          </div>
          {figure && (
            <div className="mt-3 rounded-lg bg-zinc-100 p-3 text-sm dark:bg-zinc-800" role="region" aria-label="Origen de la cifra">
              <strong>{figure.label}</strong>: {figure.value ?? "—"} {figure.unit} {figureWarning(figure.status) && <em>({figureWarning(figure.status)})</em>}
              <p>{figure.formula || "dato de origen"} · {figure.sources.map(sourceLabel).join(", ")}</p>
              <ul>{figure.records.map((r) => <li key={`${r.file}-${r.row}`}>{sourceLabel(r)} · {r.date ?? ""} · {r.amount ?? ""} · {r.description ?? r.metric ?? ""}</li>)}</ul>
            </div>
          )}
        </section>
      )}

      {events.length > 0 && (
        <section className={card} aria-label="Registro de acciones">
          <ul className="grid gap-1 text-xs">{events.slice(0, 60).map((e) => <li key={e.id}>{e.ts} · <strong>{ACTOR_LABELS[e.actor_type] ?? e.actor_type}</strong> ({e.actor_id}) · {e.action} · {e.subject}</li>)}</ul>
        </section>
      )}
    </div>
  );
}
