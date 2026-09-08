// Constantes del dominio de incidencias — deben reflejar exactamente los
// enums de services/api/app/incidents/models.py.

export const CATEGORIES = ["Queja", "Solicitud", "Fallo operativo"] as const;

export const ORIGINS = [
  { value: "customer", label: "Cliente" },
  { value: "branch", label: "Sede" },
  { value: "internal", label: "Interno" },
] as const;

// Sedes de Brasaland (CONTEXT.es.md, Hito 1) + "central".
export const BRANCHES = [
  { value: "central", label: "Central" },
  { value: "Brasaland El Poblado", label: "Brasaland El Poblado" },
  { value: "Brasaland Laureles", label: "Brasaland Laureles" },
  { value: "Brasaland Envigado", label: "Brasaland Envigado" },
  { value: "Brasaland Sabaneta", label: "Brasaland Sabaneta" },
  { value: "Brasaland Usaquén", label: "Brasaland Usaquén" },
  { value: "Brasaland Chapinero", label: "Brasaland Chapinero" },
  { value: "Brasaland Zona Rosa", label: "Brasaland Zona Rosa" },
  { value: "Brasaland Granada", label: "Brasaland Granada" },
  { value: "Brasaland Ciudad Jardín", label: "Brasaland Ciudad Jardín" },
  { value: "Brasaland Unicentro", label: "Brasaland Unicentro" },
  { value: "Brasaland Brickell", label: "Brasaland Brickell" },
  { value: "Brasaland Coral Gables", label: "Brasaland Coral Gables" },
  { value: "Brasaland Downtown", label: "Brasaland Downtown" },
  { value: "Brasaland International Drive", label: "Brasaland International Drive" },
] as const;

export const STATUS_LABELS: Record<string, string> = {
  open: "Abierta",
  in_progress: "En progreso",
  resolved: "Resuelta",
  discarded: "Descartada",
};

// Transiciones permitidas — debe reflejar ALLOWED_TRANSITIONS del backend.
export const ALLOWED_TRANSITIONS: Record<string, string[]> = {
  open: ["in_progress", "discarded"],
  in_progress: ["resolved", "discarded"],
  resolved: [],
  discarded: [],
};

export const ORIGIN_LABELS: Record<string, string> = Object.fromEntries(ORIGINS.map((o) => [o.value, o.label]));

export type Incident = {
  id: number;
  title: string;
  description: string;
  category: string;
  origin: string;
  branch: string;
  status: string;
  created_at: string;
  updated_at: string;
};

export type IncidentSummaryData = {
  total: number;
  by_status: Record<string, number>;
  by_category: Record<string, number>;
  by_origin: Record<string, number>;
  by_branch: Record<string, number>;
};
