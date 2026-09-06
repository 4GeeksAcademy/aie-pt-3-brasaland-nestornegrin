"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { apiFetch, readApiError, saveAccessToken } from "@/lib/api-client";

export function LoginForm() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const response = await apiFetch("/auth/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email, password }) }, false);
      if (!response.ok) throw new Error(await readApiError(response, "No se pudo iniciar sesión."));
      const payload = (await response.json()) as { access_token: string };
      saveAccessToken(payload.access_token);
      router.replace("/");
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "No se pudo iniciar sesión.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-5 rounded-xl border border-zinc-200 bg-white p-6 shadow-sm">
      <div><label htmlFor="email" className="block text-sm font-bold">Email</label><input id="email" required type="email" value={email} onChange={(event) => setEmail(event.target.value)} className="mt-2 w-full rounded-lg border border-zinc-300 px-3 py-2" /></div>
      <div>
        <label htmlFor="password" className="block text-sm font-bold">Contraseña</label>
        <input id="password" required type="password" value={password} onChange={(event) => setPassword(event.target.value)} className="mt-2 w-full rounded-lg border border-zinc-300 px-3 py-2" />
        <Link href="/forgot-password" className="mt-2 inline-block text-sm font-bold text-red-800">¿Olvidaste tu contraseña?</Link>
      </div>
      {error ? <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm font-semibold text-red-800">{error}</p> : null}
      <button disabled={loading} className="w-full rounded-lg bg-red-800 px-4 py-2 font-bold text-white hover:bg-red-900 disabled:opacity-60">{loading ? "Ingresando..." : "Iniciar sesión"}</button>
      <p className="text-center text-sm text-zinc-600">¿Aún no tienes cuenta? <Link href="/register" className="font-bold text-red-800">Registrarte</Link></p>
    </form>
  );
}