"use client";

import { useEffect } from "react";
import { captureError } from "@/services/telemetry-errors";

// Error Boundary de segmento: captura errores de render de cualquier página.
export default function Error({ error, unstable_retry }: { error: Error & { digest?: string }; unstable_retry: () => void }) {
  useEffect(() => {
    captureError("error_boundary", error); // telemetría: frontend_error_captured
  }, [error]);

  return (
    <div role="alert" className="rounded-xl border border-red-200 bg-red-50 p-6 text-red-800">
      <h2 className="text-lg font-black">Algo salió mal</h2>
      <p className="mt-1 text-sm">Ocurrió un error inesperado en esta pantalla.</p>
      <button type="button" onClick={() => unstable_retry()} className="mt-4 rounded-lg bg-red-800 px-4 py-2 font-bold text-white hover:bg-red-900">
        Reintentar
      </button>
    </div>
  );
}
