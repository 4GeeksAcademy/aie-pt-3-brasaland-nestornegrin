"use client";

import { useCallback, useEffect, useState } from "react";
import { KIND_LABELS, STATUS_LABELS, canSend, citationLabel, supplierContractsApi, waitingOn, type Alert, type Communication, type Reply, type Supplier } from "@/lib/supplier-contracts";

const card = "rounded-2xl border border-zinc-200 bg-white p-6 text-zinc-900 shadow-sm dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100";
const button = "rounded-lg bg-red-800 px-4 py-2 text-sm font-bold text-white hover:bg-red-900 focus:outline-none focus:ring-2 focus:ring-red-800/40 disabled:cursor-not-allowed disabled:opacity-60";
const outline = "rounded-lg border border-zinc-300 px-4 py-2 text-sm font-semibold hover:bg-zinc-100 dark:border-zinc-600 dark:hover:bg-zinc-800";
const TONE: Record<Alert["kind"], string> = { price_increase: "bg-red-50 text-red-900", contract_expiry: "bg-amber-50 text-amber-900", notice_deadline: "bg-orange-50 text-orange-900" };
const QUESTIONS = ["¿La subida de Sunshine Prime Meats está permitida por el contrato?", "¿Cuánto nos cuesta al mes la subida de Avícola Antioquia?",
  "¿Qué alternativa tenemos a Carnes del Valle y a qué precio?", "¿Cuándo tenemos que avisar a Sunshine Prime Meats si no queremos renovar?",
  "¿Cuál es el preaviso de Avícola Antioquia?", "¿Qué dice el contrato de Hortalizas La Sabana?"];
type Tab = "alerts" | "ask" | "approvals";
const msg = (e: unknown) => (e instanceof Error ? e.message : "Error inesperado.");

function Answer({ reply }: { reply: Reply }) {
  return (
    <section className={`${card} mt-4`} aria-label="Respuesta">
      <p className="text-xs text-zinc-500">Consultados: {reply.consulted.map((c) => c.replace("agent:", "")).join(" + ") || "ninguno"} · {reply.consults_used}/{reply.consults_limit} consultas</p>
      <pre className="mt-2 whitespace-pre-wrap font-sans text-sm">{reply.answer}</pre>
      {reply.citations.length > 0 && <ul className="mt-3 text-xs text-zinc-600 dark:text-zinc-300">{reply.citations.map((c) => <li key={`${c.contract_id}-${c.clause}`}>{citationLabel(c)} ({c.language.toUpperCase()}): «{c.quote}»</li>)}</ul>}
      {reply.missing.length > 0 && <div role="note" className="mt-3 rounded-lg bg-zinc-100 p-3 text-sm dark:bg-zinc-800"><strong>Lo que falta (declarado, no estimado):</strong><ul>{reply.missing.map((m) => <li key={m}>• {m}</li>)}</ul></div>}
    </section>
  );
}

export function SupplierContractsPanel() {
  const [tab, setTab] = useState<Tab>("alerts");
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [suppliers, setSuppliers] = useState<Supplier[]>([]);
  const [comms, setComms] = useState<Communication[]>([]);
  const [question, setQuestion] = useState("");
  const [supplier, setSupplier] = useState("BR-S05");
  const [reply, setReply] = useState<Reply | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const [a, s, c] = await Promise.all([supplierContractsApi.alerts(), supplierContractsApi.suppliers(), supplierContractsApi.communications()]);
      setAlerts(a); setSuppliers(s); setComms(c); setError("");
    } catch (e) { setError(msg(e)); }
  }, []);
  useEffect(() => { void Promise.resolve().then(() => load()); }, [load]);

  const run = async (fn: () => Promise<void>) => { setBusy(true); try { await fn(); setError(""); } catch (e) { setError(msg(e)); } finally { setBusy(false); } };
  const ask = (q: string) => run(async () => { setReply(await supplierContractsApi.ask(q)); setTab("ask"); });

  return (
    <div className="mx-auto grid max-w-5xl gap-4 p-4">
      <h1 className="text-2xl font-bold">Proveedores y contratos</h1>
      <p className="text-sm">Un supervisor consulta a un especialista de precios y a uno de contratos. Cada cifra y cada cláusula lleva su fuente; lo que no existe se declara. <strong>Nada sale hacia un proveedor sin aprobación humana.</strong></p>
      {error && <p role="alert" className={card}>{error}</p>}
      <nav className="flex flex-wrap gap-2" aria-label="Secciones">
        {(["alerts", "ask", "approvals"] as Tab[]).map((t) => (
          <button key={t} className={tab === t ? button : outline} onClick={() => setTab(t)} aria-pressed={tab === t}>
            {{ alerts: `Alertas (${alerts.length})`, ask: "Preguntar / brief", approvals: `Aprobaciones (${comms.filter((c) => c.status === "pending_approval" || c.status === "approved").length})` }[t]}
          </button>
        ))}
        <button className={outline} disabled={busy} onClick={() => run(async () => { await supplierContractsApi.seed(); await load(); })}>Cargar datos de prueba</button>
      </nav>

      {tab === "alerts" && (
        <section className={card} aria-label="Alertas">
          {alerts.length === 0 && <p>No hay alertas. Carga los datos de prueba para generarlas.</p>}
          <ul className="grid gap-2">
            {alerts.map((a) => (
              <li key={a.id} className={`rounded-lg px-3 py-2 text-sm ${TONE[a.kind]}`}>
                <strong>{KIND_LABELS[a.kind]}</strong> · {a.supplier_id}<p>{a.message}</p>
                {a.kind === "price_increase" && <button className={`${outline} mt-2`} onClick={() => ask(`Prepárame un brief para renegociar con ${suppliers.find((s) => s.id === a.supplier_id)?.name ?? a.supplier_id}`)}>Preparar brief</button>}
              </li>
            ))}
          </ul>
        </section>
      )}

      {tab === "ask" && (
        <section className={card} aria-label="Preguntar">
          <label className="block text-sm font-semibold" htmlFor="q">Pregunta</label>
          <textarea id="q" className="mt-1 w-full rounded-lg border border-zinc-300 p-2 text-sm dark:border-zinc-600 dark:bg-zinc-800" rows={2} value={question} onChange={(e) => setQuestion(e.target.value)} />
          <div className="mt-2 flex flex-wrap gap-2">
            <button className={button} disabled={busy || question.trim().length < 3} onClick={() => ask(question)}>Preguntar</button>
            {QUESTIONS.map((q) => <button key={q} className={outline} onClick={() => setQuestion(q)}>{q}</button>)}
          </div>
          <div className="mt-4 flex flex-wrap items-end gap-2">
            <label className="text-sm font-semibold">Brief de renegociación
              <select className="ml-2 rounded-lg border border-zinc-300 p-2 text-sm dark:border-zinc-600 dark:bg-zinc-800" value={supplier} onChange={(e) => setSupplier(e.target.value)}>
                {suppliers.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
              </select>
            </label>
            <button className={outline} disabled={busy} onClick={() => run(async () => setReply(await supplierContractsApi.brief(supplier, false)))}>Preparar brief</button>
            <button className={button} disabled={busy} onClick={() => run(async () => { setReply(await supplierContractsApi.brief(supplier, true)); await load(); })}>Brief + borrador para aprobación</button>
          </div>
          {reply && <Answer reply={reply} />}
        </section>
      )}

      {tab === "approvals" && (
        <section className={card} aria-label="Aprobaciones">
          {comms.length === 0 && <p>No hay comunicaciones a proveedores pendientes.</p>}
          <ul className="grid gap-3">
            {comms.map((c) => (
              <li key={c.id} className="rounded-lg border border-zinc-200 p-3 text-sm dark:border-zinc-700">
                <strong>{c.subject}</strong> · {STATUS_LABELS[c.status]}
                {waitingOn(c) && <p>Falta la aprobación de: {waitingOn(c)}</p>}
                <pre className="mt-2 whitespace-pre-wrap font-sans">{c.body}</pre>
                <div className="mt-2 flex gap-2">
                  {c.status === "pending_approval" && <>
                    <button className={button} disabled={busy} onClick={() => run(async () => { await supplierContractsApi.decide(c.id, "approve"); await load(); })}>Aprobar</button>
                    <button className={outline} disabled={busy} onClick={() => run(async () => { await supplierContractsApi.decide(c.id, "reject"); await load(); })}>Rechazar</button>
                  </>}
                  {canSend(c) && <button className={button} disabled={busy} onClick={() => run(async () => { await supplierContractsApi.send(c.id); await load(); })}>Enviar al proveedor</button>}
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
