import Link from "next/link";
import type { ComponentProps, ReactNode } from "react";

/** Botones de marca reutilizables (enlaces, para mantener la navegación accesible). */
const base =
  "inline-flex items-center justify-center gap-2 rounded-full px-6 py-3 text-sm font-bold uppercase tracking-wider transition duration-200 focus-visible:outline-offset-4";

const variants = {
  primary: "bg-ember text-white hover:bg-ember-dark hover:-translate-y-0.5 shadow-lg shadow-ember/30",
  amber: "bg-amber text-ink hover:bg-white hover:-translate-y-0.5",
  ghost: "border border-cream/50 text-cream hover:bg-cream hover:text-ink",
  solid: "bg-ink text-cream hover:bg-white hover:text-ink hover:-translate-y-0.5",
  dark: "border border-ink/30 text-ink hover:bg-ink hover:text-cream",
} as const;

export function ButtonLink({
  variant = "primary",
  className = "",
  ...props
}: ComponentProps<typeof Link> & { variant?: keyof typeof variants }) {
  return <Link className={`${base} ${variants[variant]} ${className}`} {...props} />;
}

export function SectionHeading({
  eyebrow,
  title,
  intro,
  tone = "dark",
  align = "left",
  id,
}: {
  eyebrow: string;
  title: ReactNode;
  intro?: ReactNode;
  tone?: "dark" | "light";
  align?: "left" | "center";
  id?: string;
}) {
  const light = tone === "light";
  return (
    <div className={align === "center" ? "mx-auto max-w-2xl text-center" : "max-w-2xl"}>
      <p className="font-display text-sm font-medium uppercase tracking-[0.3em] text-ember">{eyebrow}</p>
      <h2
        id={id}
        className={`mt-3 font-display text-4xl font-bold uppercase leading-[1.05] sm:text-5xl ${
          light ? "text-cream" : "text-ink"
        }`}
      >
        {title}
      </h2>
      {intro ? (
        <p className={`mt-4 text-base leading-relaxed sm:text-lg ${light ? "text-smoke" : "text-ink/70"}`}>{intro}</p>
      ) : null}
    </div>
  );
}

/** Cabecera interior de cada página (fondo oscuro con título grande). */
export function PageHero({
  eyebrow,
  title,
  intro,
}: {
  eyebrow: string;
  title: ReactNode;
  intro?: ReactNode;
}) {
  return (
    <section className="grain relative isolate overflow-hidden bg-ink pt-32 pb-16 text-cream sm:pt-40 sm:pb-20">
      <div
        aria-hidden="true"
        className="absolute -right-24 -top-24 h-96 w-96 rounded-full bg-ember/25 blur-3xl"
      />
      <div className="relative mx-auto max-w-6xl px-5 sm:px-8">
        <p className="font-display text-sm uppercase tracking-[0.3em] text-amber">{eyebrow}</p>
        <h1 className="mt-3 max-w-3xl font-display text-5xl font-bold uppercase leading-[1.02] sm:text-6xl lg:text-7xl">
          {title}
        </h1>
        {intro ? <p className="mt-5 max-w-2xl text-lg leading-relaxed text-smoke">{intro}</p> : null}
      </div>
    </section>
  );
}
