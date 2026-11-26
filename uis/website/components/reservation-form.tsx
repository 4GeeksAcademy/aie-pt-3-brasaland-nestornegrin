"use client";

import { useState, type FormEvent } from "react";
import { locationsByCountryAndCity } from "@/lib/locations-data";
import { SITE } from "@/lib/site-data";
import { Field, inputClass } from "./form-fields";

const ALL_LOCATIONS = Object.values(locationsByCountryAndCity).flatMap((byCity) => Object.values(byCity).flat());

const TIMES = Array.from({ length: 21 }, (_, i) => {
  const mins = 11 * 60 + i * 30; // 11:00 → 21:00
  return `${String(Math.floor(mins / 60)).padStart(2, "0")}:${String(mins % 60).padStart(2, "0")}`;
});

type Values = {
  name: string;
  email: string;
  phone: string;
  local: string;
  date: string;
  time: string;
  guests: string;
  notes: string;
};
type Errors = Partial<Record<keyof Values, string>>;

function validate(v: Values): Errors {
  const e: Errors = {};
  if (v.name.trim().split(/\s+/).filter(Boolean).length < 2) e.name = "Escribe nombre y apellido.";
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(v.email)) e.email = "Escribe un email válido.";
  if (!/^\+\d{1,3}[\s-]?\d[\d\s-]{6,}$/.test(v.phone.trim())) e.phone = "Formato: +57 300 123 4567 o +1 305 123 4567.";
  if (!v.local) e.local = "Elige un restaurante.";
  if (!v.date) e.date = "Elige una fecha.";
  else if (v.date < new Date().toISOString().slice(0, 10)) e.date = "La fecha no puede estar en el pasado.";
  if (!v.time) e.time = "Elige una hora.";
  const g = Number(v.guests);
  if (!Number.isInteger(g) || g < 1 || g > 12) e.guests = "Entre 1 y 12 personas. Para grupos mayores, llámanos.";
  return e;
}

/**
 * Solicitud de reserva. Esta web no tiene backend de reservas: al enviar se
 * abre el correo del cliente con los datos ya redactados para hola@brasaland.com
 * (y se ofrece el teléfono como alternativa inmediata).
 */
export function ReservationForm({ defaultLocal = "" }: { defaultLocal?: string }) {
  const [values, setValues] = useState<Values>({
    name: "",
    email: "",
    phone: "",
    local: ALL_LOCATIONS.includes(defaultLocal) ? defaultLocal : "",
    date: "",
    time: "",
    guests: "2",
    notes: "",
  });
  const [errors, setErrors] = useState<Errors>({});
  const [sent, setSent] = useState(false);

  const set = (k: keyof Values) => (ev: { target: { value: string } }) => setValues((p) => ({ ...p, [k]: ev.target.value }));
  const today = new Date().toISOString().slice(0, 10);

  function onSubmit(ev: FormEvent) {
    ev.preventDefault();
    const found = validate(values);
    setErrors(found);
    if (Object.keys(found).length > 0) return;
    const body = [
      `Solicitud de reserva`,
      ``,
      `Nombre: ${values.name}`,
      `Email: ${values.email}`,
      `Teléfono: ${values.phone}`,
      `Restaurante: ${values.local}`,
      `Fecha: ${values.date}  Hora: ${values.time}`,
      `Personas: ${values.guests}`,
      values.notes ? `Notas: ${values.notes}` : "",
    ].join("\n");
    const href = `mailto:${SITE.email}?subject=${encodeURIComponent(`Reserva · ${values.local} · ${values.date} ${values.time}`)}&body=${encodeURIComponent(body)}`;
    setSent(true);
    window.location.href = href;
  }

  if (sent) {
    return (
      <div role="status" className="rounded-3xl bg-white p-8 ring-1 ring-ink/5">
        <h2 className="font-display text-3xl font-bold uppercase text-ember">Casi listo</h2>
        <p className="mt-3 leading-relaxed text-ink/80">
          Hemos abierto tu correo con la solicitud ya redactada para <strong>{values.local}</strong>. Envíalo y te
          confirmaremos la reserva. ¿Prefieres hablar ahora? Llama al{" "}
          <a className="font-bold underline" href={SITE.phones.colombia.href}>{SITE.phones.colombia.display}</a> (Colombia) o al{" "}
          <a className="font-bold underline" href={SITE.phones.florida.href}>{SITE.phones.florida.display}</a> (Florida).
        </p>
        <button type="button" onClick={() => setSent(false)} className="mt-6 rounded-full border border-ink/30 px-5 py-2 text-sm font-bold hover:bg-ink hover:text-cream">
          Editar solicitud
        </button>
      </div>
    );
  }

  return (
    <form noValidate onSubmit={onSubmit} className="grid gap-5 rounded-3xl bg-white p-6 ring-1 ring-ink/5 sm:grid-cols-2 sm:p-8">
      <div className="sm:col-span-2">
        <Field id="r-local" label="Restaurante" error={errors.local}>
          {(p) => (
            <select {...p} className={inputClass} value={values.local} onChange={set("local")}>
              <option value="">Selecciona…</option>
              {Object.entries(locationsByCountryAndCity).map(([country, byCity]) =>
                Object.entries(byCity).map(([city, names]) => (
                  <optgroup key={`${country}-${city}`} label={`${city} · ${country}`}>
                    {(names ?? []).map((n) => (
                      <option key={n} value={n}>{n}</option>
                    ))}
                  </optgroup>
                )),
              )}
            </select>
          )}
        </Field>
      </div>
      <Field id="r-date" label="Fecha" error={errors.date}>
        {(p) => <input {...p} type="date" min={today} className={inputClass} value={values.date} onChange={set("date")} />}
      </Field>
      <Field id="r-time" label="Hora" error={errors.time}>
        {(p) => (
          <select {...p} className={inputClass} value={values.time} onChange={set("time")}>
            <option value="">Selecciona…</option>
            {TIMES.map((t) => (<option key={t} value={t}>{t}</option>))}
          </select>
        )}
      </Field>
      <Field id="r-guests" label="Personas" error={errors.guests}>
        {(p) => <input {...p} type="number" min={1} max={12} inputMode="numeric" className={inputClass} value={values.guests} onChange={set("guests")} />}
      </Field>
      <Field id="r-name" label="Nombre completo" error={errors.name}>
        {(p) => <input {...p} type="text" autoComplete="name" className={inputClass} value={values.name} onChange={set("name")} />}
      </Field>
      <Field id="r-email" label="Email" error={errors.email}>
        {(p) => <input {...p} type="email" autoComplete="email" className={inputClass} value={values.email} onChange={set("email")} />}
      </Field>
      <Field id="r-phone" label="Teléfono" error={errors.phone} hint="Con código de país, por ejemplo +57 300 123 4567">
        {(p) => <input {...p} type="tel" autoComplete="tel" className={inputClass} value={values.phone} onChange={set("phone")} />}
      </Field>
      <div className="sm:col-span-2">
        <Field id="r-notes" label="Notas (opcional)" hint="Alergias, celebración, silla para bebé…">
          {(p) => <textarea {...p} rows={3} className={inputClass} value={values.notes} onChange={set("notes")} />}
        </Field>
      </div>
      <div className="sm:col-span-2">
        <button type="submit" className="w-full rounded-full bg-ember px-8 py-4 text-sm font-bold uppercase tracking-wider text-white transition hover:bg-ember-dark sm:w-auto">
          Solicitar reserva
        </button>
      </div>
    </form>
  );
}
