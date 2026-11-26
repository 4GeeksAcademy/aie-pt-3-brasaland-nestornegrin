const WORDS = ["A la brasa", "Carbón y fuego vivo", "Ingredientes frescos", "Servicio cálido", "Rápido, sin sacrificar sabor", "Colombia", "Florida"];

/** Cinta decorativa en movimiento entre secciones (oculta a lectores de pantalla). */
export function MarqueeStrip() {
  const items = [...WORDS, ...WORDS];
  return (
    <div aria-hidden="true" className="overflow-hidden bg-ember py-4 text-ink">
      <div className="marquee-track font-display text-2xl font-bold uppercase tracking-widest">
        {items.map((w, i) => (
          <span key={i} className="mx-6 flex items-center gap-12 whitespace-nowrap">
            {w}
            <span className="text-ink/50">✦</span>
          </span>
        ))}
      </div>
    </div>
  );
}
