"use client";

import Link from "next/link";
import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { apiFetch, readApiError, readApiErrorDetails, saveAccessToken } from "@/lib/api-client";

type Registration = { email: string; password: string; name: string; phone: string; address: string };

export function RegisterForm() {
  const router = useRouter();
  const [form, setForm] = useState<Registration>({ email: "", password: "", name: "", phone: "", address: "" });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);

  function update(field: keyof Registration, value: string) {
    setForm((current) => ({ ...current, [field]: value }));
    setErrors((current) => ({ ...current, [field]: "" }));
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setErrors({});
    try {
      const registration = await apiFetch("/users", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(form) }, false);
      if (!registration.ok) {
        const details = await readApiErrorDetails(registration, "No se pudo crear la cuenta.");
        setErrors(details.fields);
        throw new Error(details.message);
      }
      const login = await apiFetch("/auth/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email: form.email, password: form.password }) }, false);
      if (!login.ok) throw new Error(await readApiError(login, "La cuenta se creó, pero no se pudo iniciar sesión."));
      const payload = (await login.json()) as { access_token: string };
      saveAccessToken(payload.access_token);
      router.replace("/");
    } catch (requestError) {
      setErrors({ form: requestError instanceof Error ? requestError.message : "No se pudo crear la cuenta." });
    } finally {
      setLoading(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4 rounded-xl border border-zinc-200 bg-white p-6 shadow-sm">
      <Field id="name" label="Nombre" value={form.name} onChange={(value) => update("name", value)} error={errors.name} />
      <Field id="email" label="Email" type="email" value={form.email} onChange={(value) => update("email", value)} error={errors.email} />
      <Field id="password" label="Contraseña" type="password" value={form.password} onChange={(value) => update("password", value)} error={errors.password} />
      <Field id="phone" label="Teléfono" value={form.phone} onChange={(value) => update("phone", value)} error={errors.phone} />
      <Field id="address" label="Dirección" value={form.address} onChange={(value) => update("address", value)} error={errors.address} />
      {errors.form ? <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm font-semibold text-red-800">{errors.form}</p> : null}
      <button disabled={loading} className="w-full rounded-lg bg-red-800 px-4 py-2 font-bold text-white hover:bg-red-900 disabled:opacity-60">{loading ? "Creando cuenta..." : "Crear cuenta"}</button>
      <p className="text-center text-sm text-zinc-600">¿Ya tienes cuenta? <Link href="/login" className="font-bold text-red-800">Iniciar sesión</Link></p>
    </form>
  );
}

function Field({ id, label, type = "text", value, onChange, error }: { id: string; label: string; type?: string; value: string; onChange: (value: string) => void; error?: string }) {
  return <div><label htmlFor={id} className="block text-sm font-bold">{label}</label><input id={id} required={id !== "address"} type={type} value={value} onChange={(event) => onChange(event.target.value)} className="mt-2 w-full rounded-lg border border-zinc-300 px-3 py-2" />{error ? <p className="mt-1 text-sm text-red-700">{error}</p> : null}</div>;
}