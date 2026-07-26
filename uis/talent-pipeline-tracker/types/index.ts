export interface Note {
  id: string;
  record_id: string;
  content: string;
  created_at: string;
}

export interface RecordOut {
  id: string;
  full_name: string;
  email: string;
  phone: string;
  position: string;
  linkedin_url: string | null;
  cv_url: string | null;
  status: RecordStatus;
  stage: RecordStage;
  experience_years: number;
  notes_count: number;
  applied_at: string;
  updated_at: string;
}

export interface RecordCreate {
  full_name: string;
  email: string;
  phone: string;
  position: string;
  linkedin_url?: string | null;
  cv_url?: string | null;
  experience_years: number;
}

export interface NoteCreate {
  content: string;
}

export interface RecordPatch {
  status?: RecordStatus | null;
  stage?: RecordStage | null;
}

export interface RecordsResponse {
  total: number;
  page: number;
  limit: number;
  data: RecordOut[];
}

export type RecordStatus = "received" | "in_progress" | "discarded";
export type RecordStage = "pending" | "review" | "personal_interview" | "technical_interview";

export const STATUS_OPTIONS: Array<{ value: RecordStatus; label: string }> = [
  { value: "received", label: "Recibida" },
  { value: "in_progress", label: "En curso" },
  { value: "discarded", label: "Descartada" },
];

export const STAGE_OPTIONS: Array<{ value: RecordStage; label: string }> = [
  { value: "pending", label: "Pendiente" },
  { value: "review", label: "Revisión" },
  { value: "personal_interview", label: "Entrevista personal" },
  { value: "technical_interview", label: "Entrevista técnica" },
];

export const STATUS_LABELS: Record<RecordStatus, string> = {
  received: "Recibida",
  in_progress: "En curso",
  discarded: "Descartada",
};

export const STAGE_LABELS: Record<RecordStage, string> = {
  pending: "Pendiente",
  review: "Revisión",
  personal_interview: "Entrevista personal",
  technical_interview: "Entrevista técnica",
};
