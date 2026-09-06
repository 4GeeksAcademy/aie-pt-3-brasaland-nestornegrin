"use client";

import { FormEvent, useEffect, useState } from "react";
import { apiFetch, readApiError } from "@/lib/api-client";

type Profile = { name: string; phone: string; address: string };
type Me = { email: string; role: string; profile: Profile | null };

export function ProfileForm() {
  const [me, setMe] = useState<Me | null>(null);
  const [form, setForm] = useState<Profile>({ name: "", phone: "", address: "" });
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void apiFetch("/auth/me").then(async (response) => {
      if (!response.ok) { setError(await readApiError(response, "No se pudo cargar el perfil.")); return; }
      const payload = (await response.json()) as Me;
      setMe(payload);
      setForm(payload.profile ?? { name: "", phone: "", address: "" });
    });
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setMessage(null);
    const response = await apiFetch("/profiles/me", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(form) });
    if (!response.ok) { setError(await readApiError(response, "No se pudo actualizar el perfil.")); return; }
    const profile = (await response.json()) as Profile;
    setForm(profile);
    setMe((current) => current ? { ...current, profile } : current);
    setMessage("Perfil actualizado correctamente.");
  }

  return (
    <form onSubmit={submit} className="max-w-xl space-y-5 rounded-xl border border-zinc-200 bg-white p-6 shadow-sm">
      <div className="border-b border-zinc-100 pb-4"><p className="text-xs font-bold uppercase tracking-wide text-red-800">Cuenta</p><h1 className="mt-1 text-2xl font-black">Mi perfil</h1><p className="mt-2 text-sm text-zinc-600">{me ? `${me.email} · Rol: ${me.role}` : "Cargando cuenta..."}</p></div>
      <Field label="Nombre" value={form.name} onChange={(value) => setForm({ ...form, name: value })} />
      <Field label="Teléfono" value={form.phone} onChange={(value) => setForm({ ...form, phone: value })} />
      <Field label="Dirección" value={form.address} onChange={(value) => setForm({ ...form, address: value })} />
      {error ? <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm font-semibold text-red-800">{error}</p> : null}
      {message ? <p role="status" className="rounded-lg bg-emerald-50 p-3 text-sm font-semibold text-emerald-800">{message}</p> : null}
      <button type="submit" disabled={!me} className="rounded-lg bg-red-800 px-4 py-2 font-bold text-white hover:bg-red-900 disabled:opacity-60">Guardar cambios</button>
    </form>
  );
}

function Field({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return <div><label className="block text-sm font-bold">{label}</label><input value={value} onChange={(event) => onChange(event.target.value)} className="mt-2 w-full rounded-lg border border-zinc-300 px-3 py-2" /></div>;
}