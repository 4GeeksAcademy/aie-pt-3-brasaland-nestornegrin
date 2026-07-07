export type Country = "Colombia" | "Estados Unidos";
export type City = "Medellín" | "Bogotá" | "Cali" | "Miami" | "Orlando";
export type DietaryPreference = "Sin restricciones" | "Vegetariano" | "Sin gluten" | "Otro";
export type HowDidYouHearAboutUs =
  | "Redes sociales"
  | "Recomendación"
  | "Pasando por el local"
  | "Búsqueda en internet"
  | "Otro";

export interface RestaurantLocation {
  id: number;
  country: Country;
  city: City;
  name: string;
}

export interface BrasaPointsRegistration {
  id: number;
  fullName: string;
  email: string;
  phone: string;
  country: Country;
  city: City;
  favoriteLocation?: string;
  dietaryPreferences: DietaryPreference[];
  source: HowDidYouHearAboutUs;
  birthDate: string;
  acceptedTerms: boolean;
  wantsOffers: boolean;
}

export interface AggregationSummary {
  total: number;
  average: number;
  min: number;
  max: number;
}
