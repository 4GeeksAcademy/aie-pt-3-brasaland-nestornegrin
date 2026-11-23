/** Secciones del backoffice (lista cerrada del plan) y su ruta. */
export const SECTIONS = [
  "dashboard", "suppliers", "incident_analysis", "incidents_manager", "incident_new",
  "inventory_products", "inventory_orders", "inventory_inbound", "inventory_outbound",
  "account_profile", "account_password", "login", "register", "forgot_password", "reset_password",
] as const;
export type Section = (typeof SECTIONS)[number];

const PATH_SECTIONS: Record<string, Section> = {
  "/": "dashboard",
  "/incidents": "incidents_manager",
  "/incidents/new": "incident_new",
  "/inventory/products": "inventory_products",
  "/inventory/orders": "inventory_orders",
  "/inventory/orders/inbound": "inventory_inbound",
  "/inventory/orders/outbound": "inventory_outbound",
  "/account/profile": "account_profile",
  "/account/change-password": "account_password",
  "/login": "login",
  "/register": "register",
  "/forgot-password": "forgot_password",
  "/reset-password": "reset_password",
};

/** Sección de una ruta (sin query). `null` si la ruta no es una sección conocida. */
export function sectionForPath(pathname: string): Section | null {
  const clean = pathname.length > 1 ? pathname.replace(/\/+$/, "") : pathname;
  return PATH_SECTIONS[clean] ?? null;
}

/** Sección actual según la URL del navegador (para eventos emitidos fuera de React). */
export function currentSection(): Section {
  if (typeof window === "undefined") return "dashboard";
  return sectionForPath(window.location.pathname) ?? "dashboard";
}
