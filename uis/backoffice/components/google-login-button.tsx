"use client";

import { useEffect, useState } from "react";
import { fetchProviders, startFlow } from "@/lib/federated";

/** «Continuar con Google» en el login. Solo entra quien YA vinculó Google desde su perfil: aquí nunca se crea una cuenta.
 *  No se muestra si el despliegue lo desactiva (tablets compartidas de los locales) o si Google no está configurado. */
export function GoogleLoginButton() {
  const [available, setAvailable] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let active = true;
    void fetchProviders().then((info) => {
      if (active) setAvailable(Boolean(info?.enabled && info.providers.some((p) => p.provider === "google" && p.configured)));
    });
    return () => {
      active = false;
    };
  }, []);

  if (!available) return null;

  async function start() {
    setBusy(true);
    setError(null);
    try {
      await startFlow("login");
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "No se pudo iniciar la conexión con Google.");
      setBusy(false);
    }
  }

  return (
    <div className="space-y-2 border-t border-zinc-200 pt-5">
      <button type="button" onClick={() => void start()} disabled={busy} className="w-full rounded-lg border border-zinc-300 bg-white px-4 py-2 font-bold text-zinc-900 hover:bg-zinc-50 disabled:opacity-60">
        {busy ? "Conectando con Google..." : "Continuar con Google"}
      </button>
      <p className="text-center text-xs text-zinc-500">Solo para cuentas que ya vincularon Google desde su perfil.</p>
      {error ? <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm font-semibold text-red-800">{error}</p> : null}
    </div>
  );
}
