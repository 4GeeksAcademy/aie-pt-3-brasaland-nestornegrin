import Link from "next/link";

export function HeroSection() {
  return (
    <section className="relative overflow-hidden bg-gradient-to-br from-red-900 via-red-800 to-amber-700 text-white">
      <div className="mx-auto grid max-w-6xl gap-10 px-4 py-16 sm:px-6 md:py-20 lg:grid-cols-2 lg:items-center lg:px-8">
        <article>
          <p className="mb-3 inline-block rounded-full border border-amber-200/40 px-3 py-1 text-xs font-semibold uppercase tracking-widest">
            Desde 2008
          </p>
          <h1 className="text-3xl font-black leading-tight sm:text-4xl lg:text-5xl">
            El sabor de la brasa, en cada bocado
          </h1>
          <p className="mt-4 text-base text-amber-100 sm:text-lg">
            Desde 2008 sirviendo las mejores carnes a la brasa en Colombia y
            Estados Unidos. 14 ubicaciones, una misma pasión por la calidad y
            el sabor.
          </p>
          <div className="mt-8 flex flex-col gap-3 sm:flex-row">
            <Link
              href="/brasa-points"
              className="inline-flex items-center justify-center rounded-lg bg-amber-300 px-6 py-3 text-sm font-black text-zinc-900 transition hover:bg-amber-200 focus:outline-none focus:ring-2 focus:ring-amber-200"
              aria-label="Ir al formulario de registro Brasa Points"
            >
              Únete a Brasa Points
            </Link>
            <Link
              href="#ubicaciones"
              className="inline-flex items-center justify-center rounded-lg border border-white/60 px-6 py-3 text-sm font-bold text-white transition hover:bg-white/10 focus:outline-none focus:ring-2 focus:ring-white"
              aria-label="Ver nuestras ubicaciones"
            >
              Ver ubicaciones
            </Link>
          </div>
        </article>
        <aside className="rounded-2xl border border-white/20 bg-white/10 p-6 backdrop-blur">
          <h2 className="text-lg font-bold">¿Quieres hacer un pedido?</h2>
          <p className="mt-3 text-sm text-amber-100">
            Llama a tu ubicación favorita o visítanos directamente. ¡Pronto
            tendremos pedidos en línea!
          </p>
          <p className="mt-5 text-sm font-semibold">
            14 restaurantes en Colombia y Florida
          </p>
        </aside>
      </div>
    </section>
  );
}
