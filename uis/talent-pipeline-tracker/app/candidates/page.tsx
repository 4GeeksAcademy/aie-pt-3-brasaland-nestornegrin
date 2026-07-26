import { Suspense } from "react";
import CandidatesList from "@/components/candidates/CandidatesList";

export default function CandidatesPage() {
  return (
    <Suspense fallback={<div className="mx-auto min-h-screen max-w-7xl px-6 py-24 text-center text-slate-500">Cargando pipeline...</div>}>
      <CandidatesList />
    </Suspense>
  );
}
