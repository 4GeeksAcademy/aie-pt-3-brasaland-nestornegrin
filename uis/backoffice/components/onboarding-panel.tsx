"use client";

import { useCallback, useEffect, useState } from "react";
import { canSubmit, onboardingApi, rowLabel, stageTone, type BoardRow, type Notice, type PendingApproval, type PersonView, type Reply } from "@/lib/onboarding";

const card = "rounded-2xl border border-zinc-200 bg-white p-6 text-zinc-900 shadow-sm dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100";
const button = "rounded-lg bg-red-800 px-4 py-2 text-sm font-bold text-white hover:bg-red-900 focus:outline-none focus:ring-2 focus:ring-red-800/40 disabled:cursor-not-allowed disabled:opacity-60";
const TONE = { done: "bg-green-100 text-green-900", late: "bg-red-100 text-red-900", active: "bg-amber-100 text-amber-900", todo: "bg-zinc-100 text-zinc-700" };
const fmt = (iso: string) => new Date(iso).toLocaleString("es-CO", { dateStyle: "medium", timeStyle: "short" });
type Tab = "me" | "board" | "approvals";

function Stages({ view }: { view: BoardRow }) {
  return (
    <ol className="mt-3 grid gap-2 sm:grid-cols-2">
      {view.stages.map((s) => (
        <li key={s.number} className={`rounded-lg px-3 py-2 text-sm ${TONE[stageTone(s)]}`}>
          <strong>{s.number}. {s.title}</strong> · plazo {fmt(s.deadline_at)}
          {s.requires_human_approval && <span> · aprueba: {s.approver}</span>}
          {s.last_comment && s.rejections > 0 && <p>Comentario: {s.last_comment}</p>}
        </li>
      ))}
    </ol>
  );
}

function MyProgress() {
  const [view, setView] = useState<PersonView | null>(null);
  const [error, setError] = useState("");
  const [answers, setAnswers] = useState<Record<string, number>>({});
  const [question, setQuestion] = useState("");
  const [reply, setReply] = useState<Reply | null>(null);
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    try { setView(await onboardingApi.mine()); setError(""); } catch (e) { setError(e instanceof Error ? e.message : "Error inesperado."); }
  }, []);
  useEffect(() => { void Promise.resolve().then(() => load()); }, [load]);
  if (error) return <p role="alert" className={card}>{error}</p>;
  if (!view) return <p className={card}>Cargando…</p>;
  const submit = async () => {
    setBusy(true);
    try { await onboardingApi.answers(view.id, answers); setAnswers({}); await load(); } catch (e) { setError(e instanceof Error ? e.message : "Error."); } finally { setBusy(false); }
  };
  const ask = async () => {
    setBusy(true);
    try { setReply(await onboardingApi.ask(view.id, question)); setQuestion(""); } catch (e) { setError(e instanceof Error ? e.message : "Error."); } finally { setBusy(false); }
  };
  return (
    <div className="grid gap-4">
      <section className={card} aria-label="Mi progreso">
        <h2 className="text-xl font-bold">Hola, {view.name.split(" ")[0]}: {view.progress.completed}/{view.progress.total} etapas completadas</h2>
        <p className="text-sm">Etapa actual: <strong>{view.current_stage_title}</strong>{view.waiting_on && <> · se espera: {view.waiting_on}</>}</p>
        {view.last_rejection_comment && <p role="status" className="mt-2 rounded-lg bg-red-50 p-3 text-sm text-red-900">Tu responsable pidió repasar esta etapa: {view.last_rejection_comment}</p>}
        <p className="mt-2 text-sm">Te falta: {view.remaining.join(" → ") || "nada, ¡onboarding completo!"}</p>
        <Stages view={view} />
      </section>
      {view.presentation && (
        <section className={card} aria-label="Contenido de la etapa">
          <h3 className="text-lg font-bold">{view.presentation.title}</h3>
          {view.presentation.sections.map((s) => (
            <article key={s.id} className="mt-3"><h4 className="font-bold">{s.title}</h4><p className="whitespace-pre-line text-sm">{s.body}</p><p className="text-xs text-zinc-500">Fuente oficial: {s.source}</p></article>
          ))}
        </section>
      )}
      {view.quiz && (
        <section className={card} aria-label="Comprobación">
          <h3 className="text-lg font-bold">Comprobación · intento {view.quiz.attempt} (necesitas {Math.round(view.quiz.passing_score * 100)} %)</h3>
          {view.quiz.reinforce.length > 0 && (
            <div className="mt-2 rounded-lg bg-amber-50 p-3 text-sm"><strong>Repasa estos puntos:</strong>
              {view.quiz.reinforce.map((r) => <p key={r.title} className="mt-1"><em>{r.title}</em>: {r.body}</p>)}</div>
          )}
          {view.quiz.questions.map((q) => (
            <fieldset key={q.id} className="mt-3"><legend className="font-semibold">{q.question}</legend>
              {q.options.map((o, i) => (
                <label key={i} className="block text-sm"><input type="radio" name={q.id} checked={answers[q.id] === i} onChange={() => setAnswers({ ...answers, [q.id]: i })} /> {o}</label>
              ))}
            </fieldset>
          ))}
          <button className={`${button} mt-4`} disabled={busy || !canSubmit(view.quiz.questions, answers)} onClick={submit}>Enviar comprobación</button>
        </section>
      )}
      <section className={card} aria-label="Preguntas">
        <h3 className="text-lg font-bold">¿Tienes una duda?</h3>
        <p className="text-sm">Solo respondo con el material oficial; si no está ahí, la derivo a Personas. No escribas tu documento, datos bancarios ni salario.</p>
        <input aria-label="Tu pregunta" className="mt-2 w-full rounded-lg border border-zinc-300 p-2 text-sm text-zinc-900" value={question} onChange={(e) => setQuestion(e.target.value)} maxLength={500} />
        <button className={`${button} mt-2`} disabled={busy || question.trim().length < 3} onClick={ask}>Preguntar</button>
        {reply && (
          <div role="status" className="mt-3 text-sm"><p>{reply.answer}</p>
            {reply.sources.map((s) => <p key={s.ref} className="text-xs text-zinc-500">Fuente: {s.label}</p>)}
            {reply.derived_to && <p className="font-semibold">Derivada a: {reply.derived_to}</p>}</div>
        )}
      </section>
    </div>
  );
}

function Board() {
  const [rows, setRows] = useState<BoardRow[]>([]);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const load = useCallback(async () => { try { setRows(await onboardingApi.board()); setError(""); } catch (e) { setError(e instanceof Error ? e.message : "Error."); } }, []);
  useEffect(() => { void Promise.resolve().then(() => load()); }, [load]);
  if (error) return <p role="alert" className={card}>{error}</p>;
  return (
    <section className={card} aria-label="Tablero de onboardings">
      <div className="flex items-center justify-between"><h2 className="text-xl font-bold">Onboardings activos</h2>
        <button className={button} onClick={async () => { const r = await onboardingApi.sweep(); setNote(`${r.sent.length} aviso(s) enviados`); await load(); }}>Revisar plazos</button></div>
      {note && <p role="status" className="text-sm">{note}</p>}
      {rows.map((r) => (
        <article key={r.id} className="mt-4 border-t border-zinc-200 pt-3">
          <h3 className="font-bold">{r.name} · {r.position} · {r.site}</h3>
          <p className="text-sm">Etapa {r.current_stage}: {r.current_stage_title} · {r.progress.completed}/{r.progress.total} · se espera: {r.waiting_on ?? "—"} · plazo {fmt(r.deadline_at)}</p>
          <span className={`rounded-full px-2.5 py-0.5 text-xs font-bold ${r.blocked ? TONE.late : r.overdue ? TONE.active : TONE.done}`}>{rowLabel(r)}</span>
          <Stages view={r} />
        </article>
      ))}
    </section>
  );
}

function Approvals() {
  const [items, setItems] = useState<PendingApproval[]>([]);
  const [notices, setNotices] = useState<Notice[]>([]);
  const [comment, setComment] = useState<Record<string, string>>({});
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    try { setItems(await onboardingApi.approvals()); setNotices(await onboardingApi.notifications()); setError(""); } catch (e) { setError(e instanceof Error ? e.message : "Error."); }
  }, []);
  useEffect(() => { void Promise.resolve().then(() => load()); }, [load]);
  const decide = async (item: PendingApproval, decision: "approve" | "reject") => {
    try {
      await onboardingApi.decide(item.id, { decision, comment: comment[item.id], contract_received: item.stage === 1, payroll_docs_received: item.stage === 1, accesses_confirmed: item.stage === 8 });
      await load();
    } catch (e) { setError(e instanceof Error ? e.message : "Error."); }
  };
  return (
    <div className="grid gap-4">
      {error && <p role="alert" className={card}>{error}</p>}
      <section className={card} aria-label="Aprobaciones pendientes">
        <h2 className="text-xl font-bold">Esperan tu decisión</h2>
        {items.length === 0 && <p className="text-sm">No hay aprobaciones pendientes para ti.</p>}
        {items.map((i) => (
          <article key={`${i.id}-${i.stage}`} className="mt-3 border-t border-zinc-200 pt-3">
            <h3 className="font-bold">{i.name} · etapa {i.stage}: {i.stage_title}{i.overdue && " · VENCIDA"}</h3>
            <p className="text-sm">Condición de salida: {i.exit_condition}. Plazo {fmt(i.deadline_at)}.</p>
            <input aria-label={`Comentario para ${i.name}`} placeholder="Comentario (obligatorio si rechazas)" className="mt-2 w-full rounded-lg border border-zinc-300 p-2 text-sm text-zinc-900"
              value={comment[i.id] ?? ""} onChange={(e) => setComment({ ...comment, [i.id]: e.target.value })} />
            <div className="mt-2 flex gap-2"><button className={button} onClick={() => decide(i, "approve")}>Aprobar</button>
              <button className={button} onClick={() => decide(i, "reject")}>Rechazar</button></div>
          </article>
        ))}
      </section>
      <section className={card} aria-label="Avisos"><h2 className="text-xl font-bold">Avisos</h2>
        {notices.length === 0 && <p className="text-sm">Sin avisos.</p>}
        <ul className="mt-2 list-disc pl-5 text-sm">{notices.map((n) => <li key={n.id}>{n.message}</li>)}</ul></section>
    </div>
  );
}

export function OnboardingPanel() {
  const [tab, setTab] = useState<Tab>("me");
  const tabs: [Tab, string][] = [["me", "Mi progreso"], ["board", "Tablero de Personas"], ["approvals", "Aprobaciones y avisos"]];
  return (
    <div className="mx-auto grid max-w-4xl gap-4 p-4">
      <h1 className="text-2xl font-bold">Onboarding corporativo</h1>
      <div role="tablist" className="flex gap-2">
        {tabs.map(([key, label]) => (
          <button key={key} role="tab" aria-selected={tab === key} className={`rounded-lg px-3 py-1.5 text-sm font-bold ${tab === key ? "bg-red-800 text-white" : "bg-zinc-200 text-zinc-900"}`} onClick={() => setTab(key)}>{label}</button>
        ))}
      </div>
      {tab === "me" ? <MyProgress /> : tab === "board" ? <Board /> : <Approvals />}
    </div>
  );
}
