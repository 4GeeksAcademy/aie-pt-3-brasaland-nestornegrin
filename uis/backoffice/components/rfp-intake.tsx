"use client";

import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import {
  getTicket, isLive, listTickets, reprocessTicket, statusLabel, uploadRfp, validatePdf,
  type TicketDetail, type TicketSummary,
} from "@/lib/rfp";

const POLL_MS = 3000;
const card = "rounded-2xl border border-zinc-200 bg-white p-6 text-zinc-900 shadow-sm dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100";
const button = "rounded-lg bg-red-800 px-4 py-2 text-sm font-bold text-white hover:bg-red-900 focus:outline-none focus:ring-2 focus:ring-red-800/40 disabled:cursor-not-allowed disabled:opacity-60";

function badge(t: Pick<TicketSummary, "status" | "processing">) {
  const color = t.status === "analisis_completo" ? "bg-green-100 text-green-900" : t.status === "descartado" ? "bg-zinc-200 text-zinc-800"
    : t.processing === "running" ? "bg-amber-100 text-amber-900" : "bg-red-100 text-red-900";
  return <span className={`rounded-full px-2.5 py-0.5 text-xs font-bold ${color}`}>{statusLabel(t)}</span>;
}

export function RfpIntake() {
  const [tickets, setTickets] = useState<TicketSummary[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [detail, setDetail] = useState<TicketDetail | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async () => {
    try {
      const rows = await listTickets();
      setTickets(rows);
      if (selected !== null) setDetail(await getTicket(selected));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Error inesperado.");
    }
  }, [selected]);

  useEffect(() => { void refresh(); }, [refresh]);

  // Polling mientras algún ticket siga analizándose; se detiene solo cuando todos terminaron.
  const anyLive = tickets.some(isLive);
  useEffect(() => {
    if (!anyLive) return;
    const id = setInterval(() => void refresh(), POLL_MS);
    return () => clearInterval(id);
  }, [anyLive, refresh]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const problem = validatePdf(file);
    if (problem) return setError(problem);
    setBusy(true); setError("");
    try {
      const { ticket_id } = await uploadRfp(file as File);
      setFile(null); if (input.current) input.current.value = "";
      setSelected(ticket_id);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Error inesperado.");
    } finally { setBusy(false); }
  }

  async function retry(id: number, force: boolean) {
    setError("");
    try { await reprocessTicket(id, force); await refresh(); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Error inesperado."); }
  }

  return (
    <div className="space-y-6">
      <section aria-labelledby="rfp-title" className={card}>
        <p className="text-xs font-bold uppercase tracking-wide text-red-800 dark:text-red-400">Recepción de RFPs</p>
        <h1 id="rfp-title" className="mt-1 text-2xl font-black sm:text-3xl">Sube una RFP y sigue su análisis</h1>
        <p className="mt-2 text-sm text-zinc-600 dark:text-zinc-400">
          El PDF se clasifica, se extraen sus metadatos y se reparte entre Marketing, Operaciones, Procurement y Training (solo los que apliquen).
        </p>
        <form onSubmit={submit} className="mt-4 flex flex-wrap items-end gap-3" noValidate>
          <div>
            <label htmlFor="rfp-file" className="block text-sm font-semibold">Archivo PDF (máx. 10 MB)</label>
            <input id="rfp-file" ref={input} type="file" accept="application/pdf,.pdf" disabled={busy}
              onChange={(e) => setFile(e.target.files?.[0] ?? null)} className="mt-1 block text-sm" />
          </div>
          <button type="submit" disabled={busy} className={button}>{busy ? "Subiendo…" : "Subir RFP"}</button>
        </form>
        {error && <p role="alert" className="mt-3 text-sm font-semibold text-red-800 dark:text-red-400">{error}</p>}
      </section>

      <section aria-labelledby="rfp-list" className={card}>
        <h2 id="rfp-list" className="text-lg font-black">Tickets</h2>
        {tickets.length === 0 ? <p className="mt-2 text-sm text-zinc-500">Aún no hay tickets. Sube el primer PDF.</p> : (
          <div className="mt-3 overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead><tr className="border-b text-xs uppercase text-zinc-500"><th className="py-2">#</th><th>Archivo</th><th>Cliente</th><th>Estado</th><th>Paso</th><th /></tr></thead>
              <tbody>
                {tickets.map((t) => (
                  <tr key={t.ticket_id} className={`border-b ${selected === t.ticket_id ? "bg-red-50 dark:bg-zinc-800" : ""}`}>
                    <td className="py-2 font-mono">{t.ticket_id}</td><td>{t.original_filename}</td><td>{t.client_name ?? "—"}</td>
                    <td>{badge(t)}</td><td className="text-xs text-zinc-500">{isLive(t) ? t.current_node : ""}</td>
                    <td><button type="button" className="text-sm font-bold text-red-800 underline" onClick={() => setSelected(t.ticket_id)}>Ver</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {detail && <TicketPanel detail={detail} onRetry={retry} />}
    </div>
  );
}

function TicketPanel({ detail, onRetry }: { detail: TicketDetail; onRetry: (id: number, force: boolean) => void }) {
  const meta = detail.metadata ?? {};
  const ceo = detail.handoff?.approvals?.ceo;
  const canRetry = detail.processing === "failed" || detail.processing === "stalled";
  return (
    <section aria-label={`Ticket ${detail.ticket_id}`} className={`${card} space-y-4`}>
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-lg font-black">Ticket #{detail.ticket_id}{detail.rfp_id ? ` · ${detail.rfp_id}` : ""}</h2>
        {badge(detail)}
        {canRetry && <button type="button" className={button} onClick={() => onRetry(detail.ticket_id, false)}>Reprocesar</button>}
        {detail.status === "descartado" && <button type="button" className={button} onClick={() => onRetry(detail.ticket_id, true)}>Forzar análisis (falso negativo)</button>}
      </div>

      {detail.status === "analizando" && detail.processing === "running" && <p className="text-sm">Procesando… paso actual: <b>{detail.current_node}</b></p>}
      {detail.processing_error && <p role="alert" className="text-sm text-red-800">Error: {detail.processing_error}</p>}
      {detail.status === "descartado" && (
        <div role="status" className="rounded-lg bg-zinc-100 p-3 text-sm dark:bg-zinc-800">
          <b>Documento descartado:</b> {detail.discard_reason}
        </div>
      )}

      {detail.status === "analisis_completo" && (
        <>
          {detail.summary?.headline && <p className="text-base font-semibold">{detail.summary.headline}</p>}
          <dl className="grid gap-x-6 gap-y-1 text-sm sm:grid-cols-2">
            {([["Cliente", "client_name"], ["Ubicación", "location"], ["Servicio", "service_type"], ["Alcance", "scope"],
               ["Fecha límite", "deadline"], ["Presupuesto", "budget_range"]] as const).map(([label, key]) => (
              <div key={key}><dt className="inline font-bold">{label}: </dt><dd className="inline">{String(meta[key] ?? "No indicado")}</dd></div>
            ))}
          </dl>
          {ceo?.required && <p role="status" className="text-sm font-semibold text-amber-900">Supera {ceo.threshold_usd.toLocaleString("es-CO")} USD/año: requerirá aprobación de {ceo.approver} (Parte 3).</p>}
          <div className="grid gap-4 lg:grid-cols-2">
            {detail.sections.map((s) => (
              <article key={s.department_id} className="rounded-xl border border-zinc-200 p-4 dark:border-zinc-700">
                <h3 className="font-black">{s.department} <span className="text-xs font-normal text-zinc-500">· {s.owner}</span></h3>
                {s.reason && <p className="mt-1 text-xs text-zinc-500">{s.reason}</p>}
                <h4 className="mt-3 text-xs font-bold uppercase">Aspectos clave</h4>
                <ul className="list-disc pl-5 text-sm">
                  {s.key_aspects.map((a, i) => <li key={i}><b>{a.aspect}:</b> {a.detail}{a.unverified_numbers?.length ? <em className="text-amber-800"> (cifra sin verificar: {a.unverified_numbers.join(", ")})</em> : null}{a.inferred ? <em className="text-zinc-500"> (inferido, no figura textual en el PDF)</em> : null}</li>)}
                </ul>
                {s.asks.length > 0 && <><h4 className="mt-3 text-xs font-bold uppercase">Qué pedirle a {s.owner}</h4><ul className="list-disc pl-5 text-sm">{s.asks.map((a, i) => <li key={i}>{a}</li>)}</ul></>}
                {s.open_questions.length > 0 && <><h4 className="mt-3 text-xs font-bold uppercase">Preguntas abiertas</h4><ul className="list-disc pl-5 text-sm">{s.open_questions.map((q, i) => <li key={i}>{q}</li>)}</ul></>}
              </article>
            ))}
          </div>
          {(detail.handoff?.conflicts?.length ?? 0) > 0 && <p role="alert" className="text-sm font-semibold text-red-800">Hay cifras contradictorias entre departamentos (ver handoff).</p>}
          <details className="text-sm">
            <summary className="cursor-pointer font-bold">Legibilidad (anticipa el costo de procesamiento)</summary>
            <pre className="mt-2 overflow-x-auto rounded bg-zinc-100 p-3 text-xs dark:bg-zinc-800">{JSON.stringify(detail.readability, null, 2)}</pre>
          </details>
        </>
      )}
    </section>
  );
}
