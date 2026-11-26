import { HeroSection } from "@/components/hero-section";
import { MarqueeStrip } from "@/components/marquee-strip";
import { FeaturedDishes } from "@/components/featured-dishes";
import { OurStorySection } from "@/components/our-story-section";
import { UniqueValueSection } from "@/components/unique-value-section";
import { LocationsSection } from "@/components/locations-section";
import { BrasaPointsTeaser } from "@/components/brasa-points-teaser";
import { ContactSection } from "@/components/contact-section";

export default function HomePage() {
  return (
    <main id="inicio">
      <HeroSection />
      <MarqueeStrip />
      <FeaturedDishes />
      <OurStorySection />
      <UniqueValueSection />
      <LocationsSection />
      <BrasaPointsTeaser />
      <ContactSection />
    </main>
  );
}
