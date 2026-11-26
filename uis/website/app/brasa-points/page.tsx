import type { Metadata } from "next";
import { PageHero } from "@/components/ui";
import { BrasaPointsForm } from "@/components/brasa-points-form";

export const metadata: Metadata = {
  title: "Registro Brasa Points | Brasaland",
  description:
    "Formulario oficial para registrarte en Brasa Points, el programa de fidelización digital de Brasaland.",
};

export default function BrasaPointsPage() {
  return (
    <main>
      <PageHero
        eyebrow="Brasa Points"
        title="Registro a Brasa Points"
        intro="Completa el formulario para unirte al programa de fidelización digital de Brasaland. Este registro está disponible para clientes mayores de 18 años."
      />
      <div className="mx-auto w-full max-w-4xl flex-1 px-4 py-10 sm:px-6 lg:px-8">
        <section
          aria-labelledby="form-title"
          className="rounded-2xl border border-zinc-200 bg-white p-5 shadow-sm sm:p-8"
        >
          <h2 id="form-title" className="sr-only">
            Formulario de registro
          </h2>

          <BrasaPointsForm />
        </section>
      </div>
    </main>
  );
}
