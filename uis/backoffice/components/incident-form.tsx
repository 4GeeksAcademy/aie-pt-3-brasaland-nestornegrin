"use client";

import { FormEvent, useState } from "react";
import { apiFetch, readApiErrorDetails } from "@/lib/api-client";
import { BRANCHES, CATEGORIES, ORIGINS } from "@/lib/incidents";

type FormState = {
  title: string;
  description: string;
  category: string;
  origin: string;
  branch: string;
};

const EMPTY: FormState = { title: "", description: "", category: "", origin: "", branch: "" };

const FIELD_LABELS: Record<keyof FormState, string> = {
  title: "El título es obligatorio.",
  description: "La descripción es obligatoria.",
  category: "Selecciona una categoría.",
  origin: "Selecciona un origen.",
  branch: "Selecciona una sede.",
};

function validate(form: FormState): Record<string, string> {
  const errors: Record<string, string> = {};
  (Object.keys(FIELD_LABELS) as (keyof FormState)[]).forEach((field) => {
    if (!form[field].trim()) errors[field] = FIELD_LABELS[field];
  });
  return errors;
}

export function IncidentForm() {
  const [form, setForm] = useState<FormState>(EMPTY);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);
  const [success, setSuccess] = useState(false);

  function update(field: keyof FormState, value: string) {
    setForm((current) => ({ ...current, [field]: value }));
    setErrors((current) => ({ ...current, [field]: "", form: "" }));
    setSuccess(false);
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSuccess(false);

    // Validación en el cliente antes de llamar a la API: evita una petición
    // innecesaria y muestra el error junto al campo de inmediato.
    const clientErrors = validate(form);
    if (Object.keys(clientErrors).length > 0) {
      setErrors(clientErrors);
      return;
    }

    setLoading(true);
    setErrors({});
    try {
      const response = await apiFetch("/api/incidents", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(form),
      });
      if (!response.ok) {
        const details = await readApiErrorDetails(response, "No se pudo registrar la incidencia. Inténtalo de nuevo.");
        setErrors(Object.keys(details.fields).length ? details.fields : { form: details.message });
        return;
      }
      setForm(EMPTY);
      setSuccess(true);
    } catch {
      setErrors({ form: "No se pudo conectar con el servidor. Inténtalo de nuevo en unos minutos." });
    } finally {
      setLoading(false);
    }
  }

  const branchHighlighted = form.origin === "branch";

  return (
    <form onSubmit={submit} noValidate className="max-w-xl space-y-5 rounded-xl border border-zinc-200 bg-white p-6 shadow-sm">
      <div>
        <label htmlFor="title" className="block text-sm font-bold">Título</label>
        <input id="title" required value={form.title} onChange={(event) => update("title", event.target.value)} className="mt-2 w-full rounded-lg border border-zinc-300 px-3 py-2" />
        {errors.title ? <p className="mt-1 text-sm text-red-700">{errors.title}</p> : null}
      </div>

      <div>
        <label htmlFor="description" className="block text-sm font-bold">Descripción</label>
        <textarea id="description" required rows={4} value={form.description} onChange={(event) => update("description", event.target.value)} className="mt-2 w-full rounded-lg border border-zinc-300 px-3 py-2" />
        {errors.description ? <p className="mt-1 text-sm text-red-700">{errors.description}</p> : null}
      </div>

      <div>
        <label htmlFor="category" className="block text-sm font-bold">Categoría</label>
        <select id="category" required value={form.category} onChange={(event) => update("category", event.target.value)} className="mt-2 w-full rounded-lg border border-zinc-300 px-3 py-2">
          <option value="" disabled>Selecciona una categoría</option>
          {CATEGORIES.map((category) => <option key={category} value={category}>{category}</option>)}
        </select>
        {errors.category ? <p className="mt-1 text-sm text-red-700">{errors.category}</p> : null}
      </div>

      <div>
        <label htmlFor="origin" className="block text-sm font-bold">Origen</label>
        <select id="origin" required value={form.origin} onChange={(event) => update("origin", event.target.value)} className="mt-2 w-full rounded-lg border border-zinc-300 px-3 py-2">
          <option value="" disabled>Selecciona un origen</option>
          {ORIGINS.map((origin) => <option key={origin.value} value={origin.value}>{origin.label}</option>)}
        </select>
        {errors.origin ? <p className="mt-1 text-sm text-red-700">{errors.origin}</p> : null}
      </div>

      <div className={branchHighlighted ? "rounded-lg border-2 border-red-800 bg-red-50 p-3" : ""}>
        <label htmlFor="branch" className="block text-sm font-bold">
          Sede{branchHighlighted ? " — estás reportando desde una sede" : ""}
        </label>
        <select id="branch" required value={form.branch} onChange={(event) => update("branch", event.target.value)} className="mt-2 w-full rounded-lg border border-zinc-300 px-3 py-2">
          <option value="" disabled>Selecciona una sede</option>
          {BRANCHES.map((branch) => <option key={branch.value} value={branch.value}>{branch.label}</option>)}
        </select>
        {errors.branch ? <p className="mt-1 text-sm text-red-700">{errors.branch}</p> : null}
      </div>

      {errors.form ? <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm font-semibold text-red-800">{errors.form}</p> : null}
      {success ? <p role="status" className="rounded-lg bg-emerald-50 p-3 text-sm font-semibold text-emerald-800">Incidencia registrada correctamente.</p> : null}

      <button type="submit" disabled={loading} className="w-full rounded-lg bg-red-800 px-4 py-2 font-bold text-white hover:bg-red-900 disabled:opacity-60">
        {loading ? "Registrando..." : "Registrar incidencia"}
      </button>
    </form>
  );
}
