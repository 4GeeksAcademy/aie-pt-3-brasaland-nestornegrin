"use client";

import { useEffect } from "react";
import { captureError } from "@/services/telemetry-errors";

// Error Boundary raíz: se usa cuando falla el propio layout.
export default function GlobalError({ error, unstable_retry }: { error: Error & { digest?: string }; unstable_retry: () => void }) {
  useEffect(() => {
    captureError("error_boundary", error);
  }, [error]);

  return (
    <html lang="es">
      <body>
        <h2>Algo salió mal</h2>
        <button type="button" onClick={() => unstable_retry()}>Reintentar</button>
      </body>
    </html>
  );
}
