import type { ReactNode } from "react";

/** Campo de formulario accesible: etiqueta, ayuda y mensaje de error enlazados con aria-*. */
export function Field({
  id,
  label,
  error,
  hint,
  children,
}: {
  id: string;
  label: string;
  error?: string;
  hint?: string;
  children: (props: { id: string; "aria-invalid": boolean; "aria-describedby": string | undefined }) => ReactNode;
}) {
  const describedBy = [hint ? `${id}-hint` : null, error ? `${id}-error` : null].filter(Boolean).join(" ") || undefined;
  return (
    <div>
      <label htmlFor={id} className="block text-sm font-bold uppercase tracking-wider text-ink">
        {label}
      </label>
      <div className="mt-2">{children({ id, "aria-invalid": Boolean(error), "aria-describedby": describedBy })}</div>
      {hint ? (
        <p id={`${id}-hint`} className="mt-1.5 text-xs text-ink/55">
          {hint}
        </p>
      ) : null}
      {error ? (
        <p id={`${id}-error`} role="alert" className="mt-1.5 text-sm font-semibold text-red-700">
          {error}
        </p>
      ) : null}
    </div>
  );
}

export const inputClass =
  "w-full rounded-2xl border border-ink/20 bg-white px-4 py-3 text-base text-ink placeholder:text-ink/35 focus:border-ember aria-[invalid=true]:border-red-600";
