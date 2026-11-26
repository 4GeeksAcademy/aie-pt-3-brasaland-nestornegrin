import { Reveal } from "./reveal";
import { SectionHeading } from "./ui";

const PILLARS = [
  {
    n: "01",
    title: "Calidad consistente",
    points: ["Mismas recetas y estándares en todos los locales", "Ingredientes frescos seleccionados diariamente"],
  },
  {
    n: "02",
    title: "Experiencia cálida",
    points: ["Servicio amable y atento", "Ambiente familiar en cada visita"],
  },
  {
    n: "03",
    title: "Rapidez",
    points: ["Tu comida lista en minutos", "Sin sacrificar sabor ni calidad"],
  },
];

export function UniqueValueSection() {
  return (
    <section className="bg-cream py-20 sm:py-28" aria-labelledby="unicos-title">
      <div className="mx-auto max-w-6xl px-5 sm:px-8">
        <SectionHeading id="unicos-title" eyebrow="Tres promesas" title="Lo que nos hace únicos" />
        <ul className="mt-12 grid gap-6 md:grid-cols-3">
          {PILLARS.map((p, i) => (
            <li key={p.n}>
              <Reveal delay={i * 120} className="h-full">
                <article className="h-full rounded-3xl border border-ink/10 bg-white p-8 transition hover:border-ember/50 hover:shadow-lg">
                  <span className="font-display text-6xl font-bold text-ember/25">{p.n}</span>
                  <h3 className="mt-2 font-display text-3xl font-bold uppercase">{p.title}</h3>
                  <ul className="mt-5 space-y-3 text-ink/75">
                    {p.points.map((pt) => (
                      <li key={pt} className="flex gap-3">
                        <span aria-hidden="true" className="mt-2 h-2 w-2 shrink-0 rounded-full bg-ember" />
                        {pt}
                      </li>
                    ))}
                  </ul>
                </article>
              </Reveal>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
