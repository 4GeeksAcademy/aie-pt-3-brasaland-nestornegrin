import { ButtonLink, PageHero } from "@/components/ui";

export default function NotFound() {
  return (
    <main>
      <PageHero eyebrow="Error 404" title="Esta página se nos quemó" intro="No encontramos lo que buscas, pero la parrilla sigue encendida." />
      <div className="mx-auto flex max-w-6xl flex-wrap gap-3 px-5 py-14 sm:px-8">
        <ButtonLink href="/">Volver al inicio</ButtonLink>
        <ButtonLink href="/menu" variant="dark">Ver la carta</ButtonLink>
      </div>
    </main>
  );
}
