"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { apiFetch, readApiError } from "@/lib/api-client";

export function ResetPasswordForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const token = searchParams.get("token") ?? "";

  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [invalidToken, setInvalidToken] = useState(!token);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);

    if (newPassword !== confirmPassword) {
      setError("Las contraseñas no coinciden.");
      return;
    }

    setLoading(true);
    try {
      const response = await apiFetch(
        "/auth/reset-password",
        { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ token, new_password: newPassword }) },
        false,
      );
      if (!response.ok) {
        if (response.status === 400) {
          setInvalidToken(true);
        } else {
          setError(await readApiError(response, "No se pudo restablecer la contraseña."));
        }
        return;
      }
      router.replace("/login");
    } catch {
      setError("No se pudo conectar con el servidor. Inténtalo de nuevo en unos minutos.");
    } finally {
      setLoading(false);
    }
  }

  if (invalidToken) {
    return (
      <div className="space-y-4 rounded-xl border border-zinc-200 bg-white p-6 shadow-sm">
        <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm font-semibold text-red-800">
          Este enlace de restablecimiento es inválido o ha expirado. Solicita uno nuevo.
        </p>
        <p className="text-center text-sm text-zinc-600">
          <Link href="/forgot-password" className="font-bold text-red-800">Solicitar un nuevo enlace</Link>
        </p>
      </div>
    );
  }

  return (
    <form onSubmit={submit} className="space-y-5 rounded-xl border border-zinc-200 bg-white p-6 shadow-sm">
      <div>
        <label htmlFor="new-password" className="block text-sm font-bold">Nueva contraseña</label>
        <input id="new-password" required minLength={8} type="password" value={newPassword} onChange={(event) => setNewPassword(event.target.value)} className="mt-2 w-full rounded-lg border border-zinc-300 px-3 py-2" />
      </div>
      <div>
        <label htmlFor="confirm-password" className="block text-sm font-bold">Confirmar nueva contraseña</label>
        <input id="confirm-password" required minLength={8} type="password" value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} className="mt-2 w-full rounded-lg border border-zinc-300 px-3 py-2" />
      </div>
      {error ? <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm font-semibold text-red-800">{error}</p> : null}
      <button disabled={loading} className="w-full rounded-lg bg-red-800 px-4 py-2 font-bold text-white hover:bg-red-900 disabled:opacity-60">{loading ? "Guardando..." : "Restablecer contraseña"}</button>
    </form>
  );
}
