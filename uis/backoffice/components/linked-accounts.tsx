"use client";

import { useCallback, useEffect, useState } from "react";
import { fetchAccounts, fetchProviders, startFlow, takeNotice, unlinkProvider, type LinkedAccounts } from "@/lib/federated";

/** Perfil → «Cuentas vinculadas». Vincular y desvincular viven aquí (sesión ya iniciada), nunca en la pantalla de login. */
export function LinkedAccountsPanel() {
  const [accounts, setAccounts] = useState<LinkedAccounts | null>(null);
  const [available, setAvailable] = useState(true);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setAccounts(await fetchAccounts());
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "No se pudieron cargar tus cuentas vinculadas.");
    }
  }, []);

  useEffect(() => {
    void Promise.resolve().then(async () => {
      setNotice(takeNotice()); // mensaje de «vinculación completada» dejado por el callback
      const info = await fetchProviders();
      setAvailable(Boolean(info?.enabled && info.providers.some((p) => p.provider === "google" && p.configured)));
      await load();
    });
  }, [load]);

  const google = accounts?.providers.find((p) => p.provider === "google");
  if (!accounts || !google) {
    return error ? <p role="alert" className="mt-8 max-w-xl rounded-lg bg-red-50 p-3 text-sm font-semibold text-red-800">{error}</p> : null;
  }
  const onlyMethod = google.linked && accounts.access_methods <= 1; // Google sería el ÚNICO método de acceso

  async function link() {
    setBusy(true);
    setError(null);
    try {
      await startFlow("link");
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "No se pudo iniciar la vinculación.");
      setBusy(false);
    }
  }

  async function unlink() {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      setAccounts(await unlinkProvider());
      setConfirming(false);
      setNotice("Cuenta de Google desvinculada. Ya no puedes entrar con ella.");
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "No se pudo desvincular la cuenta.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-labelledby="linked-accounts-title" className="mt-10 max-w-xl rounded-xl border border-zinc-200 bg-white p-6 shadow-sm">
      <h2 id="linked-accounts-title" className="text-xl font-black text-zinc-900">Cuentas vinculadas</h2>
      <p className="mt-1 text-sm text-zinc-600">Vincula tu cuenta de Google para poder iniciar sesión con ella. Siempre se hace desde aquí, con tu sesión iniciada.</p>
      {notice ? <p role="status" className="mt-4 rounded-lg bg-emerald-50 p-3 text-sm font-semibold text-emerald-800">{notice}</p> : null}
      {error ? <p role="alert" className="mt-4 rounded-lg bg-red-50 p-3 text-sm font-semibold text-red-800">{error}</p> : null}

      <div className="mt-5 flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="font-bold text-zinc-900">Google</p>
          <p className="text-sm text-zinc-600">
            {google.linked ? `Vinculada (${google.email_at_link_time}) desde ${new Date(google.linked_at ?? "").toLocaleDateString("es-CO")}` : "No vinculada"}
          </p>
        </div>
        {google.linked ? (
          <button type="button" disabled={busy} onClick={() => setConfirming(true)} className="rounded-lg border border-red-300 px-4 py-2 text-sm font-bold text-red-800 hover:bg-red-50 disabled:opacity-60">Desvincular</button>
        ) : available ? (
          <button type="button" disabled={busy} onClick={() => void link()} className="rounded-lg bg-red-800 px-4 py-2 text-sm font-bold text-white hover:bg-red-900 disabled:opacity-60">{busy ? "Conectando..." : "Vincular con Google"}</button>
        ) : (
          <span className="text-sm text-zinc-500">No disponible en este dispositivo</span>
        )}
      </div>

      {confirming ? (
        <div role="alertdialog" aria-label="Confirmar desvinculación" className="mt-4 rounded-lg border border-amber-300 bg-amber-50 p-4 text-sm text-amber-900">
          {onlyMethod ? (
            <p className="font-semibold">Google es tu único método de acceso: si lo desvinculas te quedarías sin forma de entrar. Crea antes una contraseña («¿Olvidaste tu contraseña?») o vincula otro proveedor.</p>
          ) : (
            <p className="font-semibold">¿Desvincular Google? Seguirás pudiendo entrar con tu contraseña.</p>
          )}
          <div className="mt-3 flex gap-3">
            <button type="button" disabled={busy || onlyMethod} onClick={() => void unlink()} className="rounded-lg bg-red-800 px-4 py-2 font-bold text-white hover:bg-red-900 disabled:opacity-50">Sí, desvincular</button>
            <button type="button" onClick={() => setConfirming(false)} className="rounded-lg border border-zinc-300 bg-white px-4 py-2 font-bold text-zinc-800">Cancelar</button>
          </div>
        </div>
      ) : null}
    </section>
  );
}
