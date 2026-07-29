import Link from "next/link";

const perks = [
  "Acumula 1 punto por cada $10.000 COP o $5 USD",
  "Canjea tus puntos por descuentos y platos gratis",
  "Ofertas exclusivas para miembros",
  "Registro 100% digital - ¡ya no más tarjetas de papel!",
];

export function BrasaPointsTeaser() {
  return (
    <section id="brasa-points" className="bg-red-900 text-white" aria-labelledby="brasa-points-title">
      <div className="mx-auto max-w-6xl px-4 py-14 sm:px-6 lg:px-8">
        <h2 id="brasa-points-title" className="text-2xl font-black sm:text-3xl">
          Gana puntos con cada visita
        </h2>
        <div className="mt-6 grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          {perks.map((perk) => (
            <article key={perk} className="rounded-lg bg-white/10 p-4">
              {perk}
            </article>
          ))}
        </div>
        <Link
          href="/brasa-points"
          className="mt-8 inline-flex rounded-lg bg-amber-300 px-6 py-3 text-sm font-black text-zinc-900 hover:bg-amber-200 focus:outline-none focus:ring-2 focus:ring-amber-200"
          aria-label="Registrarse en Brasa Points"
        >
          Registrarme ahora
        </Link>
      </div>
    </section>
  );
}
