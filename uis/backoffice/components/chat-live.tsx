"use client";

import { useEffect, useReducer, useRef, useState, type FormEvent } from "react";
import { chatReducer, connectChat, getOrCreateSessionId, initialChatState, type ChatConnection, type ChatStatus } from "@/lib/chat-ws";

const STATUS_LABEL: Record<ChatStatus, string> = {
  connecting: "Conectando…",
  live: "En vivo",
  reconnecting: "Reconectando…",
  closed: "Sin conexión",
};

export function ChatLive() {
  const [sessionId] = useState(() => getOrCreateSessionId());
  const [state, dispatch] = useReducer(chatReducer, sessionId, initialChatState);
  const [status, setStatus] = useState<ChatStatus>("connecting");
  const [text, setText] = useState("");
  const connection = useRef<ChatConnection | null>(null);
  const bottom = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const chat = connectChat({ sessionId, onEvent: dispatch, onStatus: (next) => setStatus(next) });
    connection.current = chat;
    return () => chat.close();
  }, [sessionId]);

  useEffect(() => { bottom.current?.scrollIntoView?.({ block: "end" }); }, [state.messages]);

  const generating = state.generatingId !== null;

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const value = text.trim();
    if (!value || status !== "live") return;
    // Mientras el agente responde, enviar = interrumpir y redirigir: el servidor aborta la generación y abre un turno nuevo.
    const sent = generating
      ? connection.current?.send("interrupt_requested", { new_input: value })
      : connection.current?.send("user_message", { text: value });
    if (sent) setText("");
  }

  return (
    <section aria-labelledby="chat-title" className="rounded-2xl border border-zinc-200 bg-white p-6 text-zinc-900 shadow-sm dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-xs font-bold uppercase tracking-wide text-red-800 dark:text-red-400">Manager support agent</p>
          <h1 id="chat-title" className="mt-1 text-2xl font-black sm:text-3xl">Chat en vivo</h1>
        </div>
        <span role="status" className="rounded-full border border-zinc-300 px-3 py-1 text-xs font-semibold dark:border-zinc-600" data-testid="chat-status">
          {STATUS_LABEL[status]}
        </span>
      </div>

      <div role="log" aria-live="polite" aria-busy={generating} aria-label="Conversación" className="mt-4 flex max-h-[28rem] min-h-48 flex-col gap-3 overflow-y-auto rounded-xl border border-zinc-200 p-3 dark:border-zinc-700">
        {state.hydrated && state.messages.length === 0 && (
          <p className="text-sm text-zinc-500">Pregunta lo que necesites. Si el agente se desvía, escribe y envía otro mensaje: lo interrumpe y redirige.</p>
        )}
        {state.messages.map((message) => (
          <div key={message.id} className={message.role === "user" ? "self-end" : "self-start"}>
            <p className={`max-w-prose whitespace-pre-wrap rounded-2xl px-4 py-2 text-sm ${message.role === "user" ? "bg-red-800 text-white" : "bg-zinc-100 dark:bg-zinc-800"}`}>
              {message.text}
              {message.status === "streaming" && <span aria-hidden className="ml-0.5 inline-block animate-pulse">▍</span>}
            </p>
            {message.status === "interrupted" && <p className="mt-1 text-xs font-semibold text-amber-700 dark:text-amber-400">Interrumpido</p>}
            {message.status === "failed" && <p className="mt-1 text-xs font-semibold text-red-700 dark:text-red-400">No se pudo completar la respuesta</p>}
          </div>
        ))}
        <div ref={bottom} />
      </div>

      {state.error && <p role="alert" className="mt-2 text-sm font-semibold text-red-700 dark:text-red-400">{state.error}</p>}

      <form onSubmit={submit} className="mt-3 flex flex-col gap-2 sm:flex-row">
        <label htmlFor="chat-input" className="sr-only">Mensaje</label>
        <input id="chat-input" value={text} onChange={(event) => setText(event.target.value)} maxLength={2000} autoComplete="off"
          placeholder={generating ? "Escribe para interrumpir y redirigir…" : "Escribe tu pregunta…"}
          className="min-h-11 flex-1 rounded-xl border border-zinc-300 bg-transparent px-3 text-sm dark:border-zinc-600" />
        <button type="submit" disabled={status !== "live" || !text.trim()}
          className="min-h-11 rounded-xl bg-red-800 px-5 text-sm font-bold text-white disabled:opacity-50">
          {generating ? "Interrumpir y enviar" : "Enviar"}
        </button>
      </form>
    </section>
  );
}
