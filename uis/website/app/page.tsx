import { SiteHeader } from "@/components/site-header";
import { HeroSection } from "@/components/hero-section";
import { OurStorySection } from "@/components/our-story-section";
import { UniqueValueSection } from "@/components/unique-value-section";
import { LocationsSection } from "@/components/locations-section";
import { BrasaPointsTeaser } from "@/components/brasa-points-teaser";
import { ContactSection } from "@/components/contact-section";
import { SiteFooter } from "@/components/site-footer";

export default function HomePage() {
  return (
    <>
      <SiteHeader />
      <main id="inicio" className="flex-1">
        <HeroSection />
        <OurStorySection />
        <UniqueValueSection />
        <LocationsSection />
        <BrasaPointsTeaser />
        <ContactSection />
      </main>
      <SiteFooter />
    </>
  );
}
