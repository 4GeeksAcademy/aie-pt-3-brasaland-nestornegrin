"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { createRecord } from "@/lib/api";
import { RecordCreate } from "@/types";

const initialForm: RecordCreate = {
  full_name: "",
  email: "",
  phone: "",
  position: "",
  linkedin_url: "",
  cv_url: "",
  experience_years: 0,
};

export default function NewCandidatePage() {
  const router = useRouter();
  const [form, setForm] = useState(initialForm);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  function updateField<Key extends keyof RecordCreate>(key: Key, value: RecordCreate[Key]) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setMessage(null);
    setError(null);

    if (!form.full_name || !form.email || !form.phone || !form.position || form.experience_years < 0) {
      setError("Completa los campos requeridos antes de enviar.");
      return;
    }

    setLoading(true);
    try {
      await createRecord(form);
      setMessage("Candidatura registrada correctamente.");
      router.push("/candidates");
    } catch (err) {
      setError((err as Error).message || "Error al registrar la candidatura.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="mx-auto min-h-screen max-w-4xl px-6 py-8">
      <div className="flex flex-col gap-4 rounded-3xl bg-white p-6 shadow-sm ring-1 ring-slate-200">
        <div>
          <p className="text-sm uppercase tracking-[0.25em] text-slate-500">Brasaland People & Talent</p>
          <h1 className="mt-2 text-3xl font-semibold text-slate-950">Registrar nueva candidatura</h1>
          <p className="mt-2 text-sm leading-6 text-slate-600">Agrega un nuevo candidato para que el equipo pueda seguir su proceso desde el pipeline.</p>
        </div>

        <form onSubmit={handleSubmit} className="grid gap-6">
          {message && <div className="rounded-2xl bg-emerald-50 p-4 text-sm text-emerald-700">{message}</div>}
          {error && <div className="rounded-2xl bg-red-50 p-4 text-sm text-red-700">{error}</div>}

          <div className="grid gap-4 sm:grid-cols-2">
            <label className="grid gap-2 text-sm">
              Nombre completo *
              <input value={form.full_name} onChange={(event) => updateField("full_name", event.target.value)} className="rounded-2xl border border-slate-300 px-3 py-2 text-sm outline-none focus:border-emerald-500 focus:ring-2 focus:ring-emerald-100" />
            </label>
            <label className="grid gap-2 text-sm">
              Email *
              <input type="email" value={form.email} onChange={(event) => updateField("email", event.target.value)} className="rounded-2xl border border-slate-300 px-3 py-2 text-sm outline-none focus:border-emerald-500 focus:ring-2 focus:ring-emerald-100" />
            </label>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <label className="grid gap-2 text-sm">
              Teléfono *
              <input value={form.phone} onChange={(event) => updateField("phone", event.target.value)} className="rounded-2xl border border-slate-300 px-3 py-2 text-sm outline-none focus:border-emerald-500 focus:ring-2 focus:ring-emerald-100" />
            </label>
            <label className="grid gap-2 text-sm">
              Puesto *
              <input value={form.position} onChange={(event) => updateField("position", event.target.value)} className="rounded-2xl border border-slate-300 px-3 py-2 text-sm outline-none focus:border-emerald-500 focus:ring-2 focus:ring-emerald-100" />
            </label>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <label className="grid gap-2 text-sm">
              LinkedIn
              <input value={form.linkedin_url ?? ""} onChange={(event) => updateField("linkedin_url", event.target.value || null)} className="rounded-2xl border border-slate-300 px-3 py-2 text-sm outline-none focus:border-emerald-500 focus:ring-2 focus:ring-emerald-100" />
            </label>
            <label className="grid gap-2 text-sm">
              CV URL
              <input value={form.cv_url ?? ""} onChange={(event) => updateField("cv_url", event.target.value || null)} className="rounded-2xl border border-slate-300 px-3 py-2 text-sm outline-none focus:border-emerald-500 focus:ring-2 focus:ring-emerald-100" />
            </label>
          </div>

          <label className="grid gap-2 text-sm">
            Años de experiencia *
            <input type="number" value={form.experience_years} onChange={(event) => updateField("experience_years", Number(event.target.value))} min={0} className="rounded-2xl border border-slate-300 px-3 py-2 text-sm outline-none focus:border-emerald-500 focus:ring-2 focus:ring-emerald-100" />
          </label>

          <div className="flex items-center justify-between gap-4 pt-2">
            <button type="submit" disabled={loading} className="inline-flex items-center justify-center rounded-full bg-emerald-600 px-5 py-3 text-sm font-semibold text-white transition hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-60">
              {loading ? "Registrando..." : "Registrar candidatura"}
            </button>
            <button type="button" onClick={() => router.push("/candidates")} className="text-sm font-semibold text-slate-600 underline-offset-4 hover:text-slate-900">
              Volver al listado
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
