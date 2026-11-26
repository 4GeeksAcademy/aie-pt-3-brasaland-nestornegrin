import type { Metadata, Viewport } from "next";
import localFont from "next/font/local";
import { SiteHeader } from "@/components/site-header";
import { SiteFooter } from "@/components/site-footer";
import "./globals.css";

// Tipografía de títulos autoalojada (sin peticiones a Google Fonts).
const oswald = localFont({
  src: "./fonts/Oswald-Variable.ttf",
  variable: "--font-oswald",
  weight: "200 700",
  display: "swap",
});

export const metadata: Metadata = {
  metadataBase: new URL("https://brasaland.com"),
  title: {
    default: "Brasaland | El sabor de la brasa, en cada bocado",
    template: "%s | Brasaland",
  },
  description:
    "Brasaland: cadena de restaurantes de comida a la brasa en Colombia y Estados Unidos. Conoce nuestra carta, nuestras ubicaciones y únete a Brasa Points.",
  openGraph: {
    type: "website",
    siteName: "Brasaland",
    locale: "es_CO",
    title: "Brasaland | El sabor de la brasa, en cada bocado",
    description:
      "14 restaurantes de comida a la brasa en Colombia y Florida. Carta, ubicaciones, reservas y Brasa Points.",
  },
};

export const viewport: Viewport = {
  themeColor: "#14100d",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="es" className={`${oswald.variable} h-full antialiased`}>
      <head>
        <script
          type="application/ld+json"
          // eslint-disable-next-line react/no-danger
          dangerouslySetInnerHTML={{
            __html: JSON.stringify({
              "@context": "https://schema.org",
              "@type": "Restaurant",
              name: "Brasaland",
              description:
                "Cadena de restaurantes de comida a la brasa en Colombia y Estados Unidos",
              url: "https://brasaland.com",
              foundingDate: "2008",
              servesCuisine: "Grilled food, Colombian cuisine",
              priceRange: "$$",
              address: [
                {
                  "@type": "PostalAddress",
                  addressCountry: "CO",
                  addressLocality: "Medellín",
                  addressRegion: "Antioquia",
                },
                {
                  "@type": "PostalAddress",
                  addressCountry: "US",
                  addressLocality: "Miami",
                  addressRegion: "FL",
                },
              ],
              contactPoint: {
                "@type": "ContactPoint",
                telephone: "+57-4-123-4567",
                contactType: "customer service",
                availableLanguage: ["Spanish"],
              },
              sameAs: [
                "https://instagram.com/brasaland",
                "https://facebook.com/brasaland",
              ],
            }),
          }}
        />
      </head>
      <body className="flex min-h-full flex-col bg-cream text-ink">
        <a
          href="#contenido"
          className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-[60] focus:rounded-full focus:bg-amber focus:px-5 focus:py-3 focus:font-bold focus:text-ink"
        >
          Saltar al contenido
        </a>
        <SiteHeader />
        <div id="contenido" className="flex-1">
          {children}
        </div>
        <SiteFooter />
      </body>
    </html>
  );
}
