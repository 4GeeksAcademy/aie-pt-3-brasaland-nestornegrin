"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { getNotes, getRecord, patchRecord, createNote, deleteNote, updateRecord } from "@/lib/api";
import { Note, RecordOut, RecordStage, RecordStatus, STATUS_OPTIONS, STAGE_OPTIONS } from "@/types";

function getOptionLabel(value: string, options: Array<{ value: string; label: string }>) {
  return options.find((option) => option.value === value)?.label ?? "-";
}

export default function CandidateDetailPage() {
  const { id } = useParams() as { id: string };
  const router = useRouter();
  const [record, setRecord] = useState<RecordOut | null>(null);
  const [notes, setNotes] = useState<Note[]>([]);
  const [status, setStatus] = useState<RecordStatus | "">("");
  const [stage, setStage] = useState<RecordStage | "">("");
  const [noteText, setNoteText] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [noteSaving, setNoteSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const details = useMemo(() => {
    if (!record) return [];
    return [
      { label: "Nombre", value: record.full_name },
      { label: "Email", value: record.email },
      { label: "Teléfono", value: record.phone },
      { label: "Puesto", value: record.position },
      { label: "LinkedIn", value: record.linkedin_url ?? "-" },
      { label: "CV", value: record.cv_url ?? "-" },
      { label: "Años de experiencia", value: String(record.experience_years) },
      { label: "Fecha de aplicación", value: new Date(record.applied_at).toLocaleDateString("es-ES") },
      { label: "Última actualización", value: new Date(record.updated_at).toLocaleDateString("es-ES") },
    ];
  }, [record]);

  useEffect(() => {
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const [recordResponse, notesResponse] = await Promise.all([getRecord(id), getNotes(id)]);
        setRecord(recordResponse);
        setNotes(notesResponse);
        setStatus(recordResponse.status);
        setStage(recordResponse.stage);
      } catch (err) {
        setError((err as Error).message || "Error al cargar los datos del candidato.");
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [id]);

  async function handlePatch(patch: { status?: RecordStatus | null; stage?: RecordStage | null }) {
    if (!record) return;
    setSaving(true);
    setSuccess(null);
    setError(null);
    try {
      const updated = await patchRecord(id, patch);
      setRecord(updated);
      setStatus(updated.status);
      setStage(updated.stage);
      setSuccess("Estado actualizado correctamente.");
    } catch (err) {
      setError((err as Error).message || "Error al actualizar el registro.");
    } finally {
      setSaving(false);
    }
  }

  async function handleNoteSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!noteText.trim()) {
      setError("La nota no puede estar vacía.");
      return;
    }
    setNoteSaving(true);
    setError(null);
    try {
      const note = await createNote(id, { content: noteText.trim() });
      setNotes((current) => [note, ...current]);
      setNoteText("");
      setSuccess("Nota agregada.");
    } catch (err) {
      setError((err as Error).message || "Error al agregar la nota.");
    } finally {
      setNoteSaving(false);
    }
  }

  async function handleNoteDelete(noteId: string) {
    setError(null);
    setNoteSaving(true);
    try {
      await deleteNote(id, noteId);
      setNotes((current) => current.filter((note) => note.id !== noteId));
      setSuccess("Nota eliminada.");
    } catch (err) {
      setError((err as Error).message || "Error al eliminar la nota.");
    } finally {
      setNoteSaving(false);
    }
  }

  async function handleEdit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!record) return;
    setSaving(true);
    setError(null);
    setSuccess(null);
    const form = new FormData(event.currentTarget);
    const payload = {
      full_name: String(form.get("full_name") ?? "").trim(),
      email: String(form.get("email") ?? "").trim(),
      phone: String(form.get("phone") ?? "").trim(),
      position: String(form.get("position") ?? "").trim(),
      linkedin_url: String(form.get("linkedin_url") ?? "").trim() || null,
      cv_url: String(form.get("cv_url") ?? "").trim() || null,
      experience_years: Number(form.get("experience_years")),
    };

    if (!payload.full_name || !payload.email || !payload.phone || !payload.position || Number.isNaN(payload.experience_years)) {
      setError("Todos los campos obligatorios deben completarse correctamente.");
      setSaving(false);
      return;
    }

    try {
      const updated = await updateRecord(id, payload);
      setRecord(updated);
      setSuccess("Datos del candidato actualizados.");
    } catch (err) {
      setError((err as Error).message || "Error al actualizar la candidatura.");
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return <div className="mx-auto min-h-screen max-w-6xl px-6 py-16 text-center text-slate-500">Cargando datos del candidato...</div>;
  }

  if (error) {
    return (
      <div className="mx-auto min-h-screen max-w-6xl px-6 py-16">
        <div className="rounded-3xl bg-white p-8 shadow-sm ring-1 ring-red-200">
          <p className="text-lg font-semibold text-slate-900">No se pudo cargar el candidato</p>
          <p className="mt-3 text-sm leading-6 text-slate-600">{error}</p>
          <button onClick={() => router.push("/candidates")} className="mt-6 rounded-full bg-slate-900 px-5 py-3 text-sm font-semibold text-white hover:bg-slate-700">
            Volver al listado
          </button>
        </div>
      </div>
    );
  }

  if (!record) {
    return <div className="mx-auto min-h-screen max-w-6xl px-6 py-16 text-center text-slate-500">Cargando datos del candidato...</div>;
  }

  return (
    <div className="mx-auto min-h-screen max-w-6xl px-6 py-8">
      <div className="flex flex-col gap-6">
        <div className="flex flex-col gap-4 rounded-3xl bg-white p-6 shadow-sm ring-1 ring-slate-200 md:flex-row md:items-center md:justify-between">
          <div>
            <p className="text-sm uppercase tracking-[0.25em] text-slate-500">Detalle de candidatura</p>
            <h1 className="mt-2 text-3xl font-semibold text-slate-950">{record?.full_name}</h1>
            <p className="mt-1 text-sm text-slate-600">{record?.position} · {record?.email}</p>
          </div>
          <Link href="/candidates" className="inline-flex items-center justify-center rounded-full bg-slate-100 px-5 py-3 text-sm font-semibold text-slate-800 hover:bg-slate-200">
            Volver al listado
          </Link>
        </div>

        {success && <div className="rounded-3xl bg-emerald-50 p-4 text-sm text-emerald-700">{success}</div>}
        {error && <div className="rounded-3xl bg-red-50 p-4 text-sm text-red-700">{error}</div>}

        <div className="grid gap-6 xl:grid-cols-[1.3fr_0.7fr]">
          <section className="space-y-6 rounded-3xl bg-white p-6 shadow-sm ring-1 ring-slate-200">
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="rounded-3xl border border-slate-200 bg-slate-50 p-4">
                <p className="text-xs font-semibold uppercase tracking-[0.24em] text-slate-500">Estado</p>
                <div className="mt-3 flex items-center gap-3">
                  <select value={status} onChange={(event) => { setStatus(event.target.value as RecordStatus); handlePatch({ status: event.target.value as RecordStatus }); }} className="rounded-2xl border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-emerald-500 focus:ring-2 focus:ring-emerald-100">
                    {STATUS_OPTIONS.map((option) => (
                      <option key={option.value} value={option.value}>{option.label}</option>
                    ))}
                  </select>
                  <span className="text-sm text-slate-500">{saving ? "Guardando..." : ""}</span>
                </div>
              </div>
              <div className="rounded-3xl border border-slate-200 bg-slate-50 p-4">
                <p className="text-xs font-semibold uppercase tracking-[0.24em] text-slate-500">Etapa</p>
                <div className="mt-3 flex items-center gap-3">
                  <select value={stage} onChange={(event) => { setStage(event.target.value as RecordStage); handlePatch({ stage: event.target.value as RecordStage }); }} className="rounded-2xl border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:border-emerald-500 focus:ring-2 focus:ring-emerald-100">
                    {STAGE_OPTIONS.map((option) => (
                      <option key={option.value} value={option.value}>{option.label}</option>
                    ))}
                  </select>
                  <span className="text-sm text-slate-500">{saving ? "Guardando..." : ""}</span>
                </div>
              </div>
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              {details.map((detail) => (
                <div key={detail.label} className="rounded-3xl border border-slate-200 bg-slate-50 p-4">
                  <p className="text-xs font-semibold uppercase tracking-[0.24em] text-slate-500">{detail.label}</p>
                  <p className="mt-2 text-sm text-slate-900 break-words">{detail.value}</p>
                </div>
              ))}
            </div>

            <div className="rounded-3xl border border-slate-200 bg-slate-50 p-4">
              <p className="text-xs font-semibold uppercase tracking-[0.24em] text-slate-500">Resumen</p>
              <div className="mt-4 grid gap-4 sm:grid-cols-2">
                <div className="rounded-2xl bg-white p-4 shadow-sm">
                  <p className="text-sm font-medium text-slate-700">Notas</p>
                  <p className="mt-2 text-2xl font-semibold text-slate-950">{record?.notes_count ?? 0}</p>
                </div>
                <div className="rounded-2xl bg-white p-4 shadow-sm">
                  <p className="text-sm font-medium text-slate-700">Última etapa</p>
                  <p className="mt-2 text-lg font-semibold text-slate-950">{record ? getOptionLabel(record.stage, STAGE_OPTIONS) : "-"}</p>
                </div>
              </div>
            </div>
          </section>

          <section className="space-y-6 rounded-3xl bg-white p-6 shadow-sm ring-1 ring-slate-200">
            <div>
              <p className="text-sm uppercase tracking-[0.2em] text-slate-500">Notas internas</p>
              <p className="mt-2 text-sm text-slate-600">Agrega comentarios relevantes sobre el candidato y elimina notas antiguas cuando ya no sean útiles.</p>
            </div>
            <form onSubmit={handleNoteSubmit} className="space-y-4">
              <textarea value={noteText} onChange={(event) => setNoteText(event.target.value)} rows={4} placeholder="Escribe una nota interna..." className="w-full rounded-3xl border border-slate-300 bg-white px-4 py-3 text-sm text-slate-900 outline-none focus:border-emerald-500 focus:ring-2 focus:ring-emerald-100" />
              <button type="submit" disabled={noteSaving} className="inline-flex items-center justify-center rounded-full bg-emerald-600 px-5 py-3 text-sm font-semibold text-white hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-60">
                {noteSaving ? "Guardando nota..." : "Agregar nota"}
              </button>
            </form>
            <div className="space-y-4">
              {notes.length === 0 ? (
                <div className="rounded-3xl bg-slate-50 p-4 text-sm text-slate-500">No hay notas internas aún.</div>
              ) : (
                notes.map((note) => (
                  <div key={note.id} className="rounded-3xl border border-slate-200 bg-slate-50 p-4">
                    <div className="flex items-start justify-between gap-4">
                      <div>
                        <p className="text-sm text-slate-900">{note.content}</p>
                        <p className="mt-2 text-xs text-slate-500">{new Date(note.created_at).toLocaleString("es-ES")}</p>
                      </div>
                      <button type="button" disabled={noteSaving} onClick={() => handleNoteDelete(note.id)} className="rounded-full bg-red-600 px-3 py-1 text-xs font-semibold text-white hover:bg-red-700 disabled:cursor-not-allowed disabled:opacity-60">
                        Eliminar
                      </button>
                    </div>
                  </div>
                ))
              )}
            </div>
          </section>
        </div>

        <section className="rounded-3xl bg-white p-6 shadow-sm ring-1 ring-slate-200">
          <h2 className="text-xl font-semibold text-slate-950">Editar datos del candidato</h2>
          <p className="mt-2 text-sm leading-6 text-slate-600">Corrige cualquier información de contacto o de perfil que necesite actualización.</p>
          <form onSubmit={handleEdit} className="mt-6 grid gap-6">
            <div className="grid gap-4 sm:grid-cols-2">
              <label className="grid gap-2 text-sm">
                Nombre completo *
                <input name="full_name" defaultValue={record.full_name} className="rounded-2xl border border-slate-300 px-3 py-2 text-sm outline-none focus:border-emerald-500 focus:ring-2 focus:ring-emerald-100" />
              </label>
              <label className="grid gap-2 text-sm">
                Email *
                <input name="email" type="email" defaultValue={record.email} className="rounded-2xl border border-slate-300 px-3 py-2 text-sm outline-none focus:border-emerald-500 focus:ring-2 focus:ring-emerald-100" />
              </label>
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <label className="grid gap-2 text-sm">
                Teléfono *
                <input name="phone" defaultValue={record.phone} className="rounded-2xl border border-slate-300 px-3 py-2 text-sm outline-none focus:border-emerald-500 focus:ring-2 focus:ring-emerald-100" />
              </label>
              <label className="grid gap-2 text-sm">
                Puesto *
                <input name="position" defaultValue={record.position} className="rounded-2xl border border-slate-300 px-3 py-2 text-sm outline-none focus:border-emerald-500 focus:ring-2 focus:ring-emerald-100" />
              </label>
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <label className="grid gap-2 text-sm">
                LinkedIn
                <input name="linkedin_url" defaultValue={record.linkedin_url ?? ""} className="rounded-2xl border border-slate-300 px-3 py-2 text-sm outline-none focus:border-emerald-500 focus:ring-2 focus:ring-emerald-100" />
              </label>
              <label className="grid gap-2 text-sm">
                CV URL
                <input name="cv_url" defaultValue={record.cv_url ?? ""} className="rounded-2xl border border-slate-300 px-3 py-2 text-sm outline-none focus:border-emerald-500 focus:ring-2 focus:ring-emerald-100" />
              </label>
            </div>
            <label className="grid gap-2 text-sm">
              Años de experiencia *
              <input name="experience_years" type="number" defaultValue={record.experience_years} min={0} className="rounded-2xl border border-slate-300 px-3 py-2 text-sm outline-none focus:border-emerald-500 focus:ring-2 focus:ring-emerald-100" />
            </label>
            <button type="submit" disabled={saving} className="inline-flex items-center justify-center rounded-full bg-slate-900 px-5 py-3 text-sm font-semibold text-white hover:bg-slate-700 disabled:cursor-not-allowed disabled:opacity-60">
              {saving ? "Guardando cambios..." : "Actualizar candidato"}
            </button>
          </form>
        </section>
      </div>
    </div>
  );
}
