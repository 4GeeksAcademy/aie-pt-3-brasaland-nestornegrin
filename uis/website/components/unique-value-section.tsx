const pillars = [
  {
    title: "Calidad Consistente",
    items: [
      "Mismas recetas y estándares en todos los locales.",
      "Ingredientes frescos seleccionados diariamente.",
    ],
  },
  {
    title: "Experiencia Cálida",
    items: ["Servicio amable y atento.", "Ambiente familiar en cada visita."],
  },
  {
    title: "Rapidez",
    items: [
      "Tu comida lista en minutos.",
      "Sin sacrificar sabor ni calidad.",
    ],
  },
];

export function UniqueValueSection() {
  return (
    <section className="bg-white" aria-labelledby="unicos-title">
      <div className="mx-auto max-w-6xl px-4 py-14 sm:px-6 lg:px-8">
        <h2 id="unicos-title" className="text-2xl font-black text-red-900 sm:text-3xl">
          Lo que nos hace únicos
        </h2>
        <div className="mt-8 grid gap-5 md:grid-cols-3">
          {pillars.map((pillar) => (
            <article
              key={pillar.title}
              className="rounded-xl border border-amber-200 bg-amber-50 p-6"
            >
              <h3 className="text-lg font-black text-red-800">{pillar.title}</h3>
              <ul className="mt-3 list-disc space-y-2 pl-5 text-zinc-700">
                {pillar.items.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}
