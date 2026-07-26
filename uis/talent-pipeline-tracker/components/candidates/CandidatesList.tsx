"use client";

import Link from "next/link";
import { useMemo, useState, useEffect } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { getRecords } from "@/lib/api";
import { RecordOut, STATUS_OPTIONS, STAGE_OPTIONS, STATUS_LABELS, STAGE_LABELS } from "@/types";

function Badge({ label }: { label: string }) {
  return (
    <span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-700">
      {label}
    </span>
  );
}

export default function CandidatesList() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const [records, setRecords] = useState<RecordOut[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState(searchParams.get("search") ?? "");
  const [status, setStatus] = useState(searchParams.get("status") ?? "");
  const [stage, setStage] = useState(searchParams.get("stage") ?? "");

  const queryString = useMemo(() => {
    const params = new URLSearchParams();
    if (search) params.set("search", search);
    if (status) params.set("status", status);
    if (stage) params.set("stage", stage);
    return params.toString();
  }, [search, status, stage]);

  useEffect(() => {
    async function loadRecords() {
      setLoading(true);
      setError(null);
      try {
        const response = await getRecords({ status: status || undefined, stage: stage || undefined, search: search || undefined });
        setRecords(response.data);
      } catch (err) {
        setError((err as Error).message || "Error al cargar candidaturas.");
      } finally {
        setLoading(false);
      }
    }
    loadRecords();
  }, [status, stage, search]);

  useEffect(() => {
    const current = new URL(window.location.href);
    current.search = queryString;
    router.replace(current.pathname + (queryString ? `?${queryString}` : ""));
  }, [queryString, router]);

  return (
    <div className="mx-auto flex min-h-screen max-w-7xl flex-col gap-6 px-6 py-6">
      <header className="flex flex-col gap-4 rounded-3xl bg-white p-6 shadow-sm ring-1 ring-slate-200">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p className="text-sm uppercase tracking-[0.2em] text-slate-500">Brasaland People & Talent</p>
            <h1 className="text-3xl font-semibold text-slate-950">Pipeline de candidaturas</h1>
            <p className="mt-2 text-sm leading-6 text-slate-600">
              Gestiona las candidaturas activas, filtra por etapa y estado, y abre cada perfil para actualizar progreso y notas.
            </p>
          </div>
          <Link href="/candidates/new" className="inline-flex items-center justify-center rounded-full bg-emerald-600 px-5 py-3 text-sm font-semibold text-white hover:bg-emerald-700">
            Nueva candidatura
          </Link>
        </div>
        <div className="grid gap-4 md:grid-cols-[240px_240px_minmax(160px,1fr)]">
          <label className="grid gap-2 text-sm">
            Estado
            <select value={status} onChange={(event) => setStatus(event.target.value)} className="rounded-2xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 shadow-sm outline-none focus:border-emerald-500 focus:ring-2 focus:ring-emerald-100">
              <option value="">Todos</option>
              {STATUS_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label className="grid gap-2 text-sm">
            Etapa
            <select value={stage} onChange={(event) => setStage(event.target.value)} className="rounded-2xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 shadow-sm outline-none focus:border-emerald-500 focus:ring-2 focus:ring-emerald-100">
              <option value="">Todas</option>
              {STAGE_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label className="grid gap-2 text-sm">
            Buscar por nombre o email
            <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Ej. María Pérez" className="rounded-2xl border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 shadow-sm outline-none focus:border-emerald-500 focus:ring-2 focus:ring-emerald-100" />
          </label>
        </div>
      </header>

      <section className="rounded-3xl bg-white p-6 shadow-sm ring-1 ring-slate-200">
        {loading ? (
          <div className="py-24 text-center text-slate-500">Cargando candidaturas...</div>
        ) : error ? (
          <div className="rounded-2xl border border-red-200 bg-red-50 px-4 py-6 text-red-700">{error}</div>
        ) : (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3 text-sm text-slate-500">
              <span>{records.length} candidaturas encontradas</span>
              <span>Actualizado el último filtro automáticamente</span>
            </div>

            <div className="overflow-hidden rounded-3xl border border-slate-200">
              <div className="grid grid-cols-[260px_1fr_180px_180px] gap-0 border-b border-slate-200 bg-slate-50 px-6 py-3 text-left text-xs font-semibold uppercase tracking-[0.18em] text-slate-600">
                <div>Candidato</div>
                <div>Puesto</div>
                <div>Estado</div>
                <div>Etapa</div>
              </div>
              <div className="divide-y divide-slate-200 bg-white">
                {records.map((record) => (
                  <Link key={record.id} href={`/candidates/${record.id}`} className="grid grid-cols-[260px_1fr_180px_180px] gap-0 px-6 py-4 transition hover:bg-slate-50">
                    <div>
                      <p className="font-semibold text-slate-950">{record.full_name}</p>
                      <p className="text-sm text-slate-500">{record.email}</p>
                    </div>
                    <div>
                      <p className="font-semibold text-slate-950">{record.position}</p>
                      <p className="text-sm text-slate-500">{record.phone}</p>
                    </div>
                    <div>
                      <Badge label={STATUS_LABELS[record.status]} />
                    </div>
                    <div>
                      <Badge label={STAGE_LABELS[record.stage]} />
                    </div>
                  </Link>
                ))}
                {records.length === 0 && (
                  <div className="px-6 py-20 text-center text-slate-500">No hay candidaturas que coincidan con estos filtros.</div>
                )}
              </div>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
