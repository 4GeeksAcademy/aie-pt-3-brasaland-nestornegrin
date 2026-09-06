"use client";

import { FormEvent, useState } from "react";
import { apiFetch, readApiError } from "@/lib/api-client";

export function ChangePasswordForm() {
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setMessage(null);

    if (newPassword !== confirmPassword) {
      setError("La nueva contraseña y la confirmación no coinciden.");
      return;
    }

    setLoading(true);
    try {
      const response = await apiFetch("/auth/change-password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
      });
      if (!response.ok) {
        setError(await readApiError(response, "No se pudo cambiar la contraseña."));
        return;
      }
      setMessage("Tu contraseña se actualizó correctamente.");
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
    } catch {
      setError("No se pudo conectar con el servidor. Inténtalo de nuevo en unos minutos.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <form onSubmit={submit} className="max-w-xl space-y-5 rounded-xl border border-zinc-200 bg-white p-6 shadow-sm">
      <div className="border-b border-zinc-100 pb-4">
        <p className="text-xs font-bold uppercase tracking-wide text-red-800">Cuenta</p>
        <h1 className="mt-1 text-2xl font-black">Cambiar contraseña</h1>
      </div>
      <div>
        <label htmlFor="current-password" className="block text-sm font-bold">Contraseña actual</label>
        <input id="current-password" required type="password" value={currentPassword} onChange={(event) => setCurrentPassword(event.target.value)} className="mt-2 w-full rounded-lg border border-zinc-300 px-3 py-2" />
      </div>
      <div>
        <label htmlFor="new-password" className="block text-sm font-bold">Nueva contraseña</label>
        <input id="new-password" required minLength={8} type="password" value={newPassword} onChange={(event) => setNewPassword(event.target.value)} className="mt-2 w-full rounded-lg border border-zinc-300 px-3 py-2" />
      </div>
      <div>
        <label htmlFor="confirm-password" className="block text-sm font-bold">Confirmar nueva contraseña</label>
        <input id="confirm-password" required minLength={8} type="password" value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} className="mt-2 w-full rounded-lg border border-zinc-300 px-3 py-2" />
      </div>
      {error ? <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm font-semibold text-red-800">{error}</p> : null}
      {message ? <p role="status" className="rounded-lg bg-emerald-50 p-3 text-sm font-semibold text-emerald-800">{message}</p> : null}
      <button type="submit" disabled={loading} className="rounded-lg bg-red-800 px-4 py-2 font-bold text-white hover:bg-red-900 disabled:opacity-60">{loading ? "Guardando..." : "Guardar nueva contraseña"}</button>
    </form>
  );
}
