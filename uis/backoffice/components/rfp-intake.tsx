"use client";

import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import {
  canRetryClosing, canStartApproval, decideApproval, generateResponse, generationAction, getFinalDocument, getTicket, getTrace, isLive, listTickets,
  progressLabel, reprocessTicket, retryApproval, startApproval, statusLabel, uploadRfp, validatePdf,
  type ApprovalAction, type FinalDocument, type ReviewPacket, type RfpSection, type TicketDetail, type TicketSummary, type TraceEvent,
} from "@/lib/rfp";

const POLL_MS = 3000;
const card = "rounded-2xl border border-zinc-200 bg-white p-6 text-zinc-900 shadow-sm dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100";
const button = "rounded-lg bg-red-800 px-4 py-2 text-sm font-bold text-white hover:bg-red-900 focus:outline-none focus:ring-2 focus:ring-red-800/40 disabled:cursor-not-allowed disabled:opacity-60";

function badge(t: Pick<TicketSummary, "status" | "processing" | "progress">) {
  const done = t.status === "analisis_completo" || t.status === "terminado" || (t.status === "en_evaluación" && t.processing === "idle");
  const color = done ? "bg-green-100 text-green-900" : t.status === "descartado" ? "bg-zinc-200 text-zinc-800"
    : t.status === "needs_human_review" ? "bg-orange-100 text-orange-900"
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

  async function generate(id: number, regenerate: boolean) {
    setError("");
    try { await generateResponse(id, regenerate); await refresh(); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Error inesperado."); }
  }

  async function act(task: () => Promise<void>) {
    setError("");
    try { await task(); await refresh(); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Error inesperado."); }
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
                    <td>{badge(t)}</td><td className="text-xs text-zinc-500">{isLive(t) && t.status === "analizando" ? t.current_node : progressLabel(t.progress, t.status) ?? ""}</td>
                    <td><button type="button" className="text-sm font-bold text-red-800 underline" onClick={() => setSelected(t.ticket_id)}>Ver</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {detail && <TicketPanel detail={detail} onRetry={retry} onGenerate={generate} onAct={act} />}
    </div>
  );
}

function TicketPanel({ detail, onRetry, onGenerate, onAct }: { detail: TicketDetail; onRetry: (id: number, force: boolean) => void; onGenerate: (id: number, regenerate: boolean) => void; onAct: (task: () => Promise<void>) => void }) {
  const meta = detail.metadata ?? {};
  const ceo = detail.handoff?.approvals?.ceo;
  const canRetry = detail.status === "analizando" && (detail.processing === "failed" || detail.processing === "stalled");
  const action = generationAction(detail);
  const part2 = detail.status !== "analizando" && detail.status !== "descartado";
  const progress = progressLabel(detail.progress, detail.status);
  return (
    <section aria-label={`Ticket ${detail.ticket_id}`} className={`${card} space-y-4`}>
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-lg font-black">Ticket #{detail.ticket_id}{detail.rfp_id ? ` · ${detail.rfp_id}` : ""}</h2>
        {badge(detail)}
        {canRetry && <button type="button" className={button} onClick={() => onRetry(detail.ticket_id, false)}>Reprocesar</button>}
        {action && <button type="button" className={button} onClick={() => onGenerate(detail.ticket_id, action.regenerate)}>{action.label}</button>}
        {canStartApproval(detail) && <button type="button" className={button} onClick={() => onAct(() => startApproval(detail.ticket_id))}>Abrir aprobación humana</button>}
        {canRetryClosing(detail) && <button type="button" className={button} onClick={() => onAct(() => retryApproval(detail.ticket_id))}>Reintentar cierre</button>}
        {progress && <span className="text-sm font-semibold">{progress}</span>}
        {detail.status === "descartado" && <button type="button" className={button} onClick={() => onRetry(detail.ticket_id, true)}>Forzar análisis (falso negativo)</button>}
      </div>

      {detail.status === "analizando" && detail.processing === "running" && <p className="text-sm">Procesando… paso actual: <b>{detail.current_node}</b></p>}
      {detail.processing_error && <p role="alert" className="text-sm text-red-800">Error: {detail.processing_error}</p>}
      {detail.status === "descartado" && (
        <div role="status" className="rounded-lg bg-zinc-100 p-3 text-sm dark:bg-zinc-800">
          <b>Documento descartado:</b> {detail.discard_reason}
        </div>
      )}

      {part2 && (
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
                <DraftBlock section={s} ticketId={detail.ticket_id} onAct={onAct} />
              </article>
            ))}
          </div>
          <ConflictsBanner detail={detail} />
          {detail.ceo_packet && <ApprovalForm packet={detail.ceo_packet} ticketId={detail.ticket_id} onAct={onAct} />}
          {detail.status === "terminado" && <FinalDocumentView ticketId={detail.ticket_id} />}
          <TraceView ticketId={detail.ticket_id} status={detail.status} />
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

const chip = (ok: boolean) => `rounded-full px-2 py-0.5 text-xs font-bold ${ok ? "bg-green-100 text-green-900" : "bg-red-100 text-red-900"}`;

/** Borrador de la sección + resultado de los tres evaluadores. Si agotó las iteraciones se marca como PROVISIONAL. */
export function DraftBlock({ section: s, ticketId, onAct }: { section: RfpSection; ticketId?: number; onAct?: (task: () => Promise<void>) => void }) {
  if (!s.generation_status || s.generation_status === "pendiente") return null;
  const ev = s.evaluation_results;
  return (
    <div className="mt-4 border-t pt-3" data-testid={`draft-${s.department_id}`}>
      <h4 className="text-xs font-bold uppercase">Borrador de la propuesta <span className="font-normal normal-case text-zinc-500">· iteraciones: {s.iterations ?? 0}</span></h4>
      {s.needs_human_review && (
        <p role="status" className="mt-1 rounded bg-orange-100 p-2 text-sm font-semibold text-orange-900">
          Borrador provisional — requiere revisión humana. No cumplió la evaluación tras agotar las iteraciones; no lo envíes al cliente sin corregirlo.
        </p>
      )}
      {s.generation_status === "error" && <p role="alert" className="mt-1 text-sm text-red-800">No se pudo generar: {s.generation_error}</p>}
      {s.generation_status === "generando" && <p className="mt-1 text-sm text-zinc-500">Generando…</p>}
      {s.draft_content && <pre className="mt-2 whitespace-pre-wrap rounded bg-zinc-100 p-3 font-sans text-sm dark:bg-zinc-800">{s.draft_content}</pre>}
      {ev && (
        <>
          <div className="mt-2 flex flex-wrap gap-2" aria-label="Evaluación">
            <span className={chip(ev.readability.pass)}>Legibilidad {ev.readability.pass ? "✓" : "✗"}{ev.readability.score != null ? ` (${Math.round(ev.readability.score)})` : ""}</span>
            <span className={chip(ev.relevance.pass)}>Pertinencia {ev.relevance.pass ? "✓" : "✗"}</span>
            <span className={chip(ev.compliance.pass)}>Cumplimiento {ev.compliance.pass ? "✓" : "✗"}</span>
          </div>
          {!ev.overall_pass && ev.feedback_for_generator && (
            <details className="mt-2 text-sm" open={Boolean(s.needs_human_review)}>
              <summary className="cursor-pointer font-bold">Último feedback del evaluador</summary>
              <pre className="mt-1 whitespace-pre-wrap rounded bg-zinc-100 p-2 font-sans text-xs dark:bg-zinc-800">{ev.feedback_for_generator}</pre>
            </details>
          )}
        </>
      )}
      {(s.pending_items?.length ?? 0) > 0 && <p className="mt-2 text-xs text-zinc-500">Pendiente de definir: {s.pending_items?.join("; ")}</p>}
      {s.approval_status === "aprobado" && <p role="status" className="mt-2 text-sm font-semibold text-green-900">Aprobado por {s.approver}.</p>}
      {s.escalated && <p role="alert" className="mt-2 text-sm font-semibold text-orange-900">Límite de rondas alcanzado: escalada a Camila Ospina (árbitro fijo).</p>}
      {s.review_packet && ticketId !== undefined && onAct && <ApprovalForm packet={s.review_packet} ticketId={ticketId} onAct={onAct} />}
      {(s.approval_history?.length ?? 0) > 0 && (
        <details className="mt-2 text-xs"><summary className="cursor-pointer font-bold">Historial de aprobación ({s.approval_history?.length})</summary>
          <ul className="mt-1 list-disc pl-5">{s.approval_history?.map((h, i) => <li key={i}>Ronda {h.round} · <b>{h.action}</b> · {h.approver}{h.comment ? ` — ${h.comment}` : ""}</li>)}</ul></details>
      )}
    </div>
  );
}

const ACTION_LABEL: Record<ApprovalAction, string> = { approve: "Aprobar", request_changes: "Pedir cambios", reject: "Rechazar" };

/** Punto de aprobación humana: la rama de ese departamento está pausada (interrupt) hasta que el responsable decide. */
export function ApprovalForm({ packet, ticketId, onAct }: { packet: ReviewPacket; ticketId: number; onAct: (task: () => Promise<void>) => void }) {
  const [approver, setApprover] = useState(packet.may_decide[0] ?? packet.owner);
  const [comment, setComment] = useState("");
  const id = `approval-${packet.department_id}`;
  const isCeo = packet.kind === "ceo_approval";
  const submit = (action: ApprovalAction) => onAct(async () => { await decideApproval(ticketId, packet.department_id, { action, approver, comment }); setComment(""); });
  return (
    <form aria-label={`Aprobación de ${packet.department}`} className="mt-3 space-y-2 rounded-lg border-2 border-amber-300 p-3" onSubmit={(e) => e.preventDefault()}>
      <p className="text-sm font-black">{isCeo ? "Aprobación de la CEO" : "Tu aprobación"} · ronda {packet.round}{packet.max_rounds ? ` de ${packet.max_rounds}` : ""}</p>
      {isCeo && <p className="text-sm">Valor anual estimado: <b>{packet.context.valor_anual_estimado_usd?.toLocaleString("es-CO") ?? "—"} USD</b> (umbral 50.000). Todas las secciones fueron aprobadas por sus responsables.</p>}
      {packet.previous_round && <p className="text-xs text-zinc-600">Ronda anterior: {packet.previous_round.action} — {packet.previous_round.comment}</p>}
      {(packet.conflicts?.length ?? 0) > 0 && <p className="text-xs font-semibold text-red-800">Conflicto abierto: {packet.conflicts?.map((c) => `${c.trigger_id} (árbitro: ${c.arbiter ?? "—"})`).join("; ")}</p>}
      <label htmlFor={id + "-who"} className="block text-xs font-bold">Decide</label>
      <select id={id + "-who"} value={approver} onChange={(e) => setApprover(e.target.value)} className="rounded border px-2 py-1 text-sm">
        {packet.may_decide.map((n) => <option key={n}>{n}</option>)}
      </select>
      <label htmlFor={id + "-comment"} className="block text-xs font-bold">Comentario (obligatorio al pedir cambios o rechazar; es el feedback del generador)</label>
      <textarea id={id + "-comment"} value={comment} onChange={(e) => setComment(e.target.value)} rows={2} className="w-full rounded border px-2 py-1 text-sm" />
      <div className="flex flex-wrap gap-2">
        {packet.actions.map((a) => <button key={a} type="button" className={button} onClick={() => submit(a)}>{ACTION_LABEL[a]}</button>)}
      </div>
    </form>
  );
}

function ConflictsBanner({ detail }: { detail: TicketDetail }) {
  const open = (detail.conflicts ?? []).filter((c) => c.status === "abierto");
  if (open.length === 0) return null;
  return (
    <div role="alert" className="rounded-lg bg-red-50 p-3 text-sm dark:bg-zinc-800">
      <b>Conflictos abiertos (árbitro fijo del BRIEFING):</b>
      <ul className="list-disc pl-5">{open.map((c) => <li key={c.trigger_id}><code>{c.trigger_id}</code> — árbitro: {c.arbiter}. {c.resolution}</li>)}</ul>
    </div>
  );
}

function FinalDocumentView({ ticketId }: { ticketId: number }) {
  const [doc, setDoc] = useState<FinalDocument | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { getFinalDocument(ticketId).then(setDoc).catch((e) => setError(e instanceof Error ? e.message : "Error inesperado.")); }, [ticketId]);
  if (error) return <p role="alert" className="text-sm text-red-800">{error}</p>;
  if (!doc) return null;
  const href = `data:text/markdown;charset=utf-8,${encodeURIComponent(doc.content)}`;
  return (
    <section aria-label="Documento final" className="rounded-xl border-2 border-green-600 p-4">
      <div className="flex flex-wrap items-center gap-3"><h3 className="font-black">Documento final</h3>
        <a className="text-sm font-bold text-red-800 underline" href={href} download={`propuesta-ticket-${ticketId}.md`}>Descargar (.md)</a></div>
      <pre className="mt-2 max-h-96 overflow-auto whitespace-pre-wrap rounded bg-zinc-100 p-3 font-sans text-sm dark:bg-zinc-800">{doc.content}</pre>
    </section>
  );
}

function TraceView({ ticketId, status }: { ticketId: number; status: string }) {
  const [events, setEvents] = useState<TraceEvent[] | null>(null);
  const [open, setOpen] = useState(false);
  useEffect(() => { if (open) getTrace(ticketId).then(setEvents).catch(() => setEvents([])); }, [open, ticketId, status]);
  return (
    <details className="text-sm" onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}>
      <summary className="cursor-pointer font-bold">Trazabilidad: qué agente hizo qué y en qué orden</summary>
      {open && events && (
        <ol className="mt-2 max-h-80 list-decimal overflow-auto pl-6 text-xs">
          {events.map((ev) => <li key={ev.seq}><span className="font-mono">{ev.ts.slice(11, 19)}</span> · P{ev.part} · <b>{ev.agent}</b> · {ev.node}
            {ev.output ? <span className="text-zinc-500"> → {JSON.stringify(ev.output).slice(0, 140)}</span> : null}</li>)}
        </ol>
      )}
    </details>
  );
}
