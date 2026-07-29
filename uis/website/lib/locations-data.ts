// Single source of truth for the Brasa Points cascading fields
// (Pais -> Ciudad -> Ubicacion favorita).
// See .agents/rules/brasa-points-cascading-fields.md at the monorepo root:
// this data must match CONTEXT.es.md exactly and must not be duplicated
// elsewhere. validation.js (Hito 1) is kept as historical reference only.
import type { City, Country } from "../../../src/types/models";

export const cityOptionsByCountry: Record<Country, City[]> = {
  Colombia: ["Medellín", "Bogotá", "Cali"],
  "Estados Unidos": ["Miami", "Orlando"],
};

export const locationsByCountryAndCity: Record<Country, Partial<Record<City, string[]>>> = {
  Colombia: {
    Medellín: [
      "Brasaland El Poblado",
      "Brasaland Laureles",
      "Brasaland Envigado",
      "Brasaland Sabaneta",
    ],
    Bogotá: [
      "Brasaland Usaquén",
      "Brasaland Chapinero",
      "Brasaland Zona Rosa",
    ],
    Cali: [
      "Brasaland Granada",
      "Brasaland Ciudad Jardín",
      "Brasaland Unicentro",
    ],
  },
  "Estados Unidos": {
    Miami: ["Brasaland Brickell", "Brasaland Coral Gables"],
    Orlando: ["Brasaland Downtown", "Brasaland International Drive"],
  },
};

export const dietaryPreferenceOptions = [
  "Sin restricciones",
  "Vegetariano",
  "Sin gluten",
  "Otro",
] as const;

export const sourceOptions = [
  "Redes sociales",
  "Recomendación",
  "Pasando por el local",
  "Búsqueda en internet",
  "Otro",
] as const;
