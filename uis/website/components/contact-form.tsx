"use client";

import { useState, type FormEvent } from "react";
import { SITE } from "@/lib/site-data";
import { Field, inputClass } from "./form-fields";

const SUBJECTS = ["Consulta general", "Eventos y grupos", "Comentarios sobre mi visita", "Alianzas y proveedores", "Trabaja con nosotros"];

type Values = { name: string; email: string; subject: string; message: string };

/** Mensaje de contacto: abre el correo del cliente con el texto redactado (sin backend). */
export function ContactForm() {
  const [v, setV] = useState<Values>({ name: "", email: "", subject: SUBJECTS[0], message: "" });
  const [errors, setErrors] = useState<Partial<Record<keyof Values, string>>>({});
  const [sent, setSent] = useState(false);
  const set = (k: keyof Values) => (ev: { target: { value: string } }) => setV((p) => ({ ...p, [k]: ev.target.value }));

  function onSubmit(ev: FormEvent) {
    ev.preventDefault();
    const e: typeof errors = {};
    if (v.name.trim().split(/\s+/).filter(Boolean).length < 2) e.name = "Escribe nombre y apellido.";
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(v.email)) e.email = "Escribe un email válido.";
    if (v.message.trim().length < 10) e.message = "Cuéntanos un poco más (mínimo 10 caracteres).";
    setErrors(e);
    if (Object.keys(e).length) return;
    setSent(true);
    window.location.href = `mailto:${SITE.email}?subject=${encodeURIComponent(v.subject)}&body=${encodeURIComponent(`${v.message}\n\n— ${v.name} (${v.email})`)}`;
  }

  if (sent) {
    return (
      <div role="status" className="rounded-3xl bg-white p-8 ring-1 ring-ink/5">
        <h2 className="font-display text-3xl font-bold uppercase text-ember">¡Gracias, {v.name.split(" ")[0]}!</h2>
        <p className="mt-3 text-ink/80">Se ha abierto tu correo con el mensaje listo. Envíalo y te responderemos pronto.</p>
        <button type="button" onClick={() => setSent(false)} className="mt-6 rounded-full border border-ink/30 px-5 py-2 text-sm font-bold hover:bg-ink hover:text-cream">
          Volver al formulario
        </button>
      </div>
    );
  }

  return (
    <form noValidate onSubmit={onSubmit} className="grid gap-5 rounded-3xl bg-white p-6 ring-1 ring-ink/5 sm:p-8">
      <Field id="c-name" label="Nombre completo" error={errors.name}>
        {(p) => <input {...p} type="text" autoComplete="name" className={inputClass} value={v.name} onChange={set("name")} />}
      </Field>
      <Field id="c-email" label="Email" error={errors.email}>
        {(p) => <input {...p} type="email" autoComplete="email" className={inputClass} value={v.email} onChange={set("email")} />}
      </Field>
      <Field id="c-subject" label="Asunto">
        {(p) => (
          <select {...p} className={inputClass} value={v.subject} onChange={set("subject")}>
            {SUBJECTS.map((s) => (<option key={s}>{s}</option>))}
          </select>
        )}
      </Field>
      <Field id="c-message" label="Mensaje" error={errors.message}>
        {(p) => <textarea {...p} rows={5} className={inputClass} value={v.message} onChange={set("message")} />}
      </Field>
      <button type="submit" className="w-full rounded-full bg-ember px-8 py-4 text-sm font-bold uppercase tracking-wider text-white transition hover:bg-ember-dark sm:w-auto sm:justify-self-start">
        Enviar mensaje
      </button>
    </form>
  );
}
