"use client";

import { useState, type FormEvent } from "react";
import { askKnowledge, KnowledgeQueryError, MAX_QUESTION_LENGTH } from "@/lib/knowledge";

type Status = "idle" | "loading" | "success" | "error";

// Preguntas de ejemplo del BRIEFING (Hito 7): sirven de atajo para probar el asistente.
const EXAMPLE_QUESTIONS = [
  "¿Cuántos puntos necesito para el nivel Oro?",
  "¿La Costilla BBQ tiene alérgenos?",
  "¿Cuándo se genera el pedido semanal a proveedores?",
];

export function KnowledgeQueryForm() {
  const [question, setQuestion] = useState("");
  const [status, setStatus] = useState<Status>("idle");
  const [answer, setAnswer] = useState("");
  const [askedQuestion, setAskedQuestion] = useState("");
  const [error, setError] = useState("");

  async function submit(text: string) {
    const trimmed = text.trim();
    if (!trimmed) {
      setStatus("error");
      setError("Escribe una pregunta para consultar la base de conocimiento.");
      return;
    }
    setStatus("loading");
    setError("");
    setAskedQuestion(trimmed);
    try {
      setAnswer(await askKnowledge(trimmed));
      setStatus("success");
    } catch (caught) {
      setAnswer("");
      setError(
        caught instanceof KnowledgeQueryError ? caught.message : "Ocurrió un error inesperado. Inténtalo de nuevo.",
      );
      setStatus("error");
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (status !== "loading") void submit(question);
  }

  const loading = status === "loading";

  return (
    <section
      aria-labelledby="knowledge-title"
      className="rounded-2xl border border-zinc-200 bg-white p-6 text-zinc-900 shadow-sm dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
    >
      <p className="text-xs font-bold uppercase tracking-wide text-red-800 dark:text-red-400">Base de conocimiento</p>
      <h1 id="knowledge-title" className="mt-1 text-2xl font-black sm:text-3xl">
        Pregúntale al asistente de Brasaland
      </h1>
      <p className="mt-2 text-sm text-zinc-600 dark:text-zinc-400">
        Responde con la información oficial de Brasa Points, desperdicio, alérgenos y pedidos a proveedores.
      </p>

      <form onSubmit={handleSubmit} className="mt-6 space-y-3" noValidate>
        <label htmlFor="knowledge-question" className="block text-sm font-semibold">
          Tu pregunta
        </label>
        <textarea
          id="knowledge-question"
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          maxLength={MAX_QUESTION_LENGTH}
          rows={3}
          placeholder="Ej.: ¿Cuántos puntos necesito para el nivel Oro?"
          disabled={loading}
          className="w-full rounded-lg border border-zinc-300 bg-white p-3 text-sm text-zinc-900 placeholder:text-zinc-400 focus:border-red-800 focus:outline-none focus:ring-2 focus:ring-red-800/30 disabled:opacity-60 dark:border-zinc-600 dark:bg-zinc-800 dark:text-zinc-100 dark:placeholder:text-zinc-500"
        />

        <div className="flex flex-wrap items-center gap-3">
          <button
            type="submit"
            disabled={loading}
            className="rounded-lg bg-red-800 px-5 py-2.5 text-sm font-bold text-white hover:bg-red-900 focus:outline-none focus:ring-2 focus:ring-red-800/40 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {loading ? "Consultando..." : "Consultar"}
          </button>
          <span className="text-xs text-zinc-500 dark:text-zinc-400">Prueba con:</span>
          {EXAMPLE_QUESTIONS.map((example) => (
            <button
              key={example}
              type="button"
              disabled={loading}
              onClick={() => setQuestion(example)}
              className="rounded-full border border-zinc-300 px-3 py-1 text-xs text-zinc-700 hover:border-red-800 hover:text-red-800 disabled:opacity-60 dark:border-zinc-600 dark:text-zinc-300 dark:hover:border-red-400 dark:hover:text-red-400"
            >
              {example}
            </button>
          ))}
        </div>
      </form>

      <div className="mt-6" aria-live="polite" aria-busy={loading}>
        {loading && (
          <p role="status" className="rounded-lg border border-zinc-200 p-4 text-sm text-zinc-600 dark:border-zinc-700 dark:text-zinc-300">
            Consultando la base de conocimiento...
          </p>
        )}

        {status === "error" && (
          <div
            role="alert"
            className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800 dark:border-red-900 dark:bg-red-950 dark:text-red-200"
          >
            <p className="font-semibold">{error}</p>
            {askedQuestion && (
              <button type="button" onClick={() => void submit(askedQuestion)} className="mt-2 font-bold underline">
                Reintentar
              </button>
            )}
          </div>
        )}

        {status === "success" && (
          <article className="rounded-xl border border-zinc-200 bg-zinc-50 p-4 dark:border-zinc-700 dark:bg-zinc-800">
            <h2 className="text-xs font-bold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
              Respuesta a: {askedQuestion}
            </h2>
            <p className="mt-2 whitespace-pre-wrap text-sm leading-relaxed">{answer}</p>
          </article>
        )}
      </div>
    </section>
  );
}
