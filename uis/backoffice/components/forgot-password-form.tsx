"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";
import { apiFetch } from "@/lib/api-client";

const CONFIRMATION_MESSAGE = "Si esa dirección está registrada, recibirás un enlace para restablecer tu contraseña en breve.";

export function ForgotPasswordForm() {
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setError(null);
    try {
      // No autenticado: la petición es pública. La API siempre responde 200,
      // exista o no el email, así que la confirmación se muestra igual en
      // ambos casos (evita que el frontend filtre qué direcciones existen).
      await apiFetch("/auth/forgot-password", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email }) }, false);
      setSubmitted(true);
    } catch {
      setError("No se pudo conectar con el servidor. Inténtalo de nuevo en unos minutos.");
    } finally {
      setLoading(false);
    }
  }

  if (submitted) {
    return (
      <div className="space-y-4 rounded-xl border border-zinc-200 bg-white p-6 shadow-sm">
        <p role="status" className="rounded-lg bg-emerald-50 p-3 text-sm font-semibold text-emerald-800">{CONFIRMATION_MESSAGE}</p>
        <p className="text-center text-sm text-zinc-600"><Link href="/login" className="font-bold text-red-800">Volver a iniciar sesión</Link></p>
      </div>
    );
  }

  return (
    <form onSubmit={submit} className="space-y-5 rounded-xl border border-zinc-200 bg-white p-6 shadow-sm">
      <p className="text-sm text-zinc-600">Introduce el email de tu cuenta y te enviaremos un enlace para elegir una nueva contraseña.</p>
      <div>
        <label htmlFor="email" className="block text-sm font-bold">Email</label>
        <input id="email" required type="email" value={email} onChange={(event) => setEmail(event.target.value)} className="mt-2 w-full rounded-lg border border-zinc-300 px-3 py-2" />
      </div>
      {error ? <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm font-semibold text-red-800">{error}</p> : null}
      <button disabled={loading} className="w-full rounded-lg bg-red-800 px-4 py-2 font-bold text-white hover:bg-red-900 disabled:opacity-60">{loading ? "Enviando..." : "Enviar enlace de restablecimiento"}</button>
      <p className="text-center text-sm text-zinc-600"><Link href="/login" className="font-bold text-red-800">Volver a iniciar sesión</Link></p>
    </form>
  );
}
