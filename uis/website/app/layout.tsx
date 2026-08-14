import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Brasaland | El sabor de la brasa, en cada bocado",
  description:
    "Brasaland: cadena de restaurantes de comida a la brasa en Colombia y Estados Unidos. Conoce nuestras ubicaciones y unete a Brasa Points.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="es" className="h-full antialiased">
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
      <body className="min-h-full flex flex-col bg-amber-50 text-zinc-900">
        {children}
      </body>
    </html>
  );
}
