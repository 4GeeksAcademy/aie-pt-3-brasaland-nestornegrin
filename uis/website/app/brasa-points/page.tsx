import type { Metadata } from "next";
import Link from "next/link";
import { BrasaPointsForm } from "@/components/brasa-points-form";

export const metadata: Metadata = {
  title: "Registro Brasa Points | Brasaland",
  description:
    "Formulario oficial para registrarte en Brasa Points, el programa de fidelización digital de Brasaland.",
};

export default function BrasaPointsPage() {
  return (
    <>
      <header className="border-b border-amber-200 bg-white">
        <div className="mx-auto flex w-full max-w-4xl items-center justify-between px-4 py-4 sm:px-6 lg:px-8">
          <Link
            href="/"
            className="text-2xl font-black tracking-tight text-red-800"
            aria-label="Volver a la página principal de Brasaland"
          >
            Brasaland
          </Link>
          <Link
            href="/"
            className="rounded-full border border-red-700 px-4 py-2 text-sm font-bold text-red-700 hover:bg-red-700 hover:text-white focus:outline-none focus:ring-2 focus:ring-red-800"
          >
            Volver al inicio
          </Link>
        </div>
      </header>

      <main className="mx-auto w-full max-w-4xl flex-1 px-4 py-8 sm:px-6 lg:px-8">
        <section
          aria-labelledby="form-title"
          className="rounded-2xl border border-zinc-200 bg-white p-5 shadow-sm sm:p-8"
        >
          <h1 id="form-title" className="text-2xl font-black text-red-900 sm:text-3xl">
            Registro a Brasa Points
          </h1>
          <p className="mt-3 text-sm leading-relaxed text-zinc-700 sm:text-base">
            Completa el formulario para unirte al programa de fidelización
            digital de Brasaland. Este registro está disponible para clientes
            mayores de 18 años.
          </p>

          <BrasaPointsForm />
        </section>
      </main>
    </>
  );
}
