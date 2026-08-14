const regions = [
  {
    name: "Colombia",
    summary: "10 restaurantes en Medellín, Bogotá y Cali",
    hours: "Horario: Lun-Dom 11:00 - 22:00",
  },
  {
    name: "Estados Unidos (Florida)",
    summary: "4 restaurantes en Miami y Orlando",
    hours: "Horario: Mon-Sun 11:00 AM - 10:00 PM",
  },
];

export function LocationsSection() {
  return (
    <section
      id="ubicaciones"
      className="mx-auto max-w-6xl px-4 py-14 sm:px-6 lg:px-8"
      aria-labelledby="ubicaciones-title"
    >
      <h2 id="ubicaciones-title" className="text-2xl font-black text-red-900 sm:text-3xl">
        Nuestras Ubicaciones
      </h2>
      <div className="mt-8 grid gap-6 md:grid-cols-2">
        {regions.map((region) => (
          <article
            key={region.name}
            className="rounded-xl border border-zinc-200 bg-white p-6 shadow-sm"
          >
            <h3 className="text-xl font-black text-zinc-900">{region.name}</h3>
            <p className="mt-3 text-zinc-700">{region.summary}</p>
            <p className="mt-2 font-semibold text-zinc-800">{region.hours}</p>
          </article>
        ))}
      </div>
    </section>
  );
}
