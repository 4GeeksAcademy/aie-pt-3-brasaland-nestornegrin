/**
 * Datos de contenido del sitio público (navegación, contacto, carta).
 *
 * Importante:
 *  - Las ubicaciones y el formulario de Brasa Points siguen usando
 *    `lib/locations-data.ts` (fuente única de verdad, no se duplica aquí).
 *  - La carta es de EJEMPLO, coherente con una cadena de comida a la brasa
 *    colombiana. Sustituirla por la carta real cuando Marketing la facilite.
 */

export const SITE = {
  name: "Brasaland",
  url: "https://brasaland.com",
  email: "hola@brasaland.com",
  phones: {
    colombia: { label: "Colombia", display: "+57 4 123 4567", href: "tel:+5741234567" },
    florida: { label: "Florida", display: "+1 305 123 4567", href: "tel:+13051234567" },
  },
  social: {
    instagram: "https://instagram.com/brasaland",
    facebook: "https://facebook.com/brasaland",
  },
  hours: {
    colombia: "Lun–Dom · 11:00 – 22:00",
    florida: "Mon–Sun · 11:00 AM – 10:00 PM",
  },
} as const;

export const NAV_LINKS = [
  { href: "/", label: "Inicio" },
  { href: "/menu", label: "Menú" },
  { href: "/ubicaciones", label: "Ubicaciones" },
  { href: "/nuestra-historia", label: "Historia" },
  { href: "/brasa-points", label: "Brasa Points" },
  { href: "/contacto", label: "Contacto" },
] as const;

/** Fotografías (Unsplash). Cada <FoodImage> tiene un degradado de respaldo si alguna falla. */
const u = (id: string, w = 1200) =>
  `https://images.unsplash.com/photo-${id}?auto=format&fit=crop&w=${w}&q=75`;

export const PHOTOS = {
  hero: u("1544025162-d76694265947", 1800),
  grill: u("1529193591184-b1d58069ecdd", 1400),
  skewers: u("1555939594-58d7cb561ad1", 1000),
  steak: u("1600891964092-4316c288032e", 1000),
  steak2: u("1558030006-450675393462", 1000),
  dining: u("1517248135467-4c7edcad34c4", 1400),
  plate: u("1414235077428-338989a2e8c0", 1000),
} as const;

export type MenuCategoryId = "brasas" | "compartir" | "acompanantes" | "bebidas" | "postres";

export type Dish = {
  id: string;
  name: string;
  description: string;
  category: MenuCategoryId;
  /** Precios por país: COP en Colombia, USD en Florida. */
  priceCOP: number;
  priceUSD: number;
  image?: string;
  tags?: ("recomendado" | "vegetariano" | "sin gluten" | "picante")[];
};

export const MENU_CATEGORIES: { id: MenuCategoryId; label: string; blurb: string }[] = [
  { id: "brasas", label: "A la brasa", blurb: "Carnes y aves cocinadas sobre carbón, a fuego vivo." },
  { id: "compartir", label: "Para compartir", blurb: "Tablas y entradas pensadas para la mesa." },
  { id: "acompanantes", label: "Acompañantes", blurb: "Lo que hace redondo cada plato." },
  { id: "bebidas", label: "Bebidas", blurb: "Frescas, caseras y de la tierra." },
  { id: "postres", label: "Postres", blurb: "El final dulce que se queda en la memoria." },
];

export const DISHES: Dish[] = [
  {
    id: "churrasco",
    name: "Churrasco Brasaland",
    description:
      "Corte de res a la brasa, jugoso por dentro y sellado por fuera. Con papa criolla, chimichurri de la casa y arepa.",
    category: "brasas",
    priceCOP: 58000,
    priceUSD: 27,
    image: PHOTOS.steak,
    tags: ["recomendado", "sin gluten"],
  },
  {
    id: "pollo-brasa",
    name: "Medio pollo a la brasa",
    description:
      "Marinado 24 horas con ajo, comino y cerveza negra. Piel crocante, carne tierna. Acompañado de yuca y ensalada.",
    category: "brasas",
    priceCOP: 39000,
    priceUSD: 19,
    image: PHOTOS.skewers,
    tags: ["recomendado"],
  },
  {
    id: "costillas",
    name: "Costillas BBQ ahumadas",
    description:
      "Costillar de cerdo cocinado lento y terminado a la brasa con glaseado de panela y chipotle.",
    category: "brasas",
    priceCOP: 62000,
    priceUSD: 29,
    image: PHOTOS.steak2,
    tags: ["picante"],
  },
  {
    id: "chorizo",
    name: "Chorizo santarrosano",
    description: "Chorizo artesanal a la parrilla con limón, arepa de maíz y hogao casero.",
    category: "brasas",
    priceCOP: 28000,
    priceUSD: 14,
    tags: ["sin gluten"],
  },
  {
    id: "portobello",
    name: "Portobello a la brasa",
    description: "Hongo portobello asado con queso campesino, chimichurri y vegetales de temporada.",
    category: "brasas",
    priceCOP: 34000,
    priceUSD: 17,
    tags: ["vegetariano", "sin gluten"],
  },
  {
    id: "picada",
    name: "Picada Brasaland",
    description:
      "Tabla para 3–4 personas: res, cerdo, pollo, chorizo, morcilla, papa criolla, yuca y patacones.",
    category: "compartir",
    priceCOP: 118000,
    priceUSD: 54,
    image: PHOTOS.grill,
    tags: ["recomendado"],
  },
  {
    id: "empanadas",
    name: "Empanadas criollas (x4)",
    description: "Crocantes, rellenas de carne desmechada y papa, con ají de la casa.",
    category: "compartir",
    priceCOP: 18000,
    priceUSD: 9,
    tags: ["picante"],
  },
  {
    id: "provoleta",
    name: "Queso a la brasa con bocadillo",
    description: "Queso costeño dorado al fuego con bocadillo de guayaba y pan tostado.",
    category: "compartir",
    priceCOP: 24000,
    priceUSD: 12,
    tags: ["vegetariano"],
  },
  {
    id: "patacones",
    name: "Patacones con hogao",
    description: "Plátano verde dos veces frito, con hogao y guacamole.",
    category: "acompanantes",
    priceCOP: 14000,
    priceUSD: 7,
    tags: ["vegetariano", "sin gluten"],
  },
  {
    id: "yuca",
    name: "Yuca frita",
    description: "Dorada y crocante por fuera, suave por dentro, con salsa rosada.",
    category: "acompanantes",
    priceCOP: 11000,
    priceUSD: 6,
    tags: ["vegetariano", "sin gluten"],
  },
  {
    id: "arepa",
    name: "Arepa con queso",
    description: "Arepa de maíz asada a la brasa, rellena de queso fundido.",
    category: "acompanantes",
    priceCOP: 9000,
    priceUSD: 5,
    tags: ["vegetariano", "sin gluten"],
  },
  {
    id: "ensalada",
    name: "Ensalada de la huerta",
    description: "Mezcla fresca con aguacate, tomate, cebolla encurtida y vinagreta de limón.",
    category: "acompanantes",
    priceCOP: 15000,
    priceUSD: 8,
    tags: ["vegetariano", "sin gluten"],
  },
  {
    id: "limonada-coco",
    name: "Limonada de coco",
    description: "Cremosa y fría, la favorita de la casa.",
    category: "bebidas",
    priceCOP: 12000,
    priceUSD: 6,
    tags: ["recomendado", "vegetariano"],
  },
  {
    id: "jugos",
    name: "Jugos naturales",
    description: "Lulo, maracuyá, mora o mango, en agua o en leche.",
    category: "bebidas",
    priceCOP: 10000,
    priceUSD: 5,
    tags: ["vegetariano"],
  },
  {
    id: "cafe",
    name: "Café de origen colombiano",
    description: "Filtrado o espresso, de pequeños productores.",
    category: "bebidas",
    priceCOP: 7000,
    priceUSD: 4,
    tags: ["vegetariano"],
  },
  {
    id: "brevas",
    name: "Brevas con arequipe",
    description: "Brevas en almíbar, arequipe y queso fresco. Un clásico.",
    category: "postres",
    priceCOP: 16000,
    priceUSD: 8,
    tags: ["vegetariano"],
  },
  {
    id: "tres-leches",
    name: "Tres leches de la casa",
    description: "Bizcocho húmedo con crema de leche y toque de canela.",
    category: "postres",
    priceCOP: 17000,
    priceUSD: 8,
    tags: ["vegetariano"],
  },
];

/** Platos que se destacan en la home. */
export const FEATURED_DISH_IDS = ["churrasco", "pollo-brasa", "picada"] as const;

export function formatPrice(dish: Dish, market: "CO" | "US"): string {
  return market === "CO"
    ? new Intl.NumberFormat("es-CO", { style: "currency", currency: "COP", maximumFractionDigits: 0 }).format(dish.priceCOP)
    : new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(dish.priceUSD);
}
