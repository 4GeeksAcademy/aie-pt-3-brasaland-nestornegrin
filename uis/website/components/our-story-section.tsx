import Image from "next/image";

export function OurStorySection() {
  return (
    <section
      className="mx-auto max-w-6xl px-4 py-14 sm:px-6 lg:px-8"
      id="menu"
      aria-labelledby="historia-title"
    >
      <div className="grid items-center gap-8 lg:grid-cols-2">
        <article>
          <h2 id="historia-title" className="text-2xl font-black text-red-900 sm:text-3xl">
            Nuestra Historia
          </h2>
          <p className="mt-4 leading-relaxed text-zinc-700">
            Fundada en Medellín en 2008, Brasaland comenzó como un sueño
            familiar: compartir el auténtico sabor de la carne a la brasa con
            calidad constante y servicio cálido. Hoy somos 14 restaurantes en
            dos países, pero mantenemos la misma receta de éxito: productos
            frescos, técnicas tradicionales, y pasión por cada plato que
            servimos.
          </p>
        </article>
        <figure className="relative h-72 w-full overflow-hidden rounded-2xl shadow-lg sm:h-80">
          <Image
            src="https://images.unsplash.com/photo-1544025162-d76694265947?auto=format&fit=crop&w=1200&q=80"
            alt="Chef preparando carne a la brasa en la cocina de un restaurante Brasaland"
            fill
            sizes="(min-width: 1024px) 50vw, 100vw"
            className="object-cover"
          />
        </figure>
      </div>
    </section>
  );
}
