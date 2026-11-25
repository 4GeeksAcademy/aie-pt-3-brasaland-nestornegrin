"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { apiFetch, readApiError, saveAccessToken } from "@/lib/api-client";
import { callbackUri, forgetFlow, NOT_LINKED_FALLBACK, recallFlow, setNotice } from "@/lib/federated";
import { startTelemetrySession } from "@/services/telemetry";

type Outcome = { kind: "working" } | { kind: "error"; message: string; offerRegister?: boolean };

/** Vuelta desde Google. VINCULAR (con sesión) o ENTRAR (solo cuentas ya vinculadas). El `state` lo valida la API. */
export function FederatedCallback() {
  const router = useRouter();
  const params = useSearchParams();
  const started = useRef(false); // en desarrollo React ejecuta los efectos dos veces: el `code` solo se canjea una vez
  const [outcome, setOutcome] = useState<Outcome>({ kind: "working" });

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    const code = params.get("code");
    const state = params.get("state");
    const flow = recallFlow();
    forgetFlow();
    if (params.get("error") || !code || !state || !flow) {
      void Promise.resolve().then(() => setOutcome({ kind: "error", message: params.get("error") ? "Cancelaste el acceso con Google." : "La solicitud no es válida o ha caducado. Vuelve a intentarlo." }));
      return;
    }
    void (async () => {
      try {
        const response = await apiFetch(`/auth/federated/google/${flow}/complete`, {
          method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ code, state, redirect_uri: callbackUri() }),
        }, flow === "link");
        if (flow === "login") {
          if (response.status === 403 && response.headers.get("X-Federated-Error") === "not_linked") {
            setOutcome({ kind: "error", message: await readApiError(response, NOT_LINKED_FALLBACK), offerRegister: true });
            return;
          }
          if (!response.ok) throw new Error(await readApiError(response, "No se pudo iniciar sesión con Google."));
          saveAccessToken(((await response.json()) as { access_token: string }).access_token);
          startTelemetrySession();
          router.replace("/");
          return;
        }
        if (!response.ok) throw new Error(await readApiError(response, "No se pudo vincular la cuenta."));
        setNotice(((await response.json()) as { message: string }).message);
        router.replace("/account/profile");
      } catch (requestError) {
        setOutcome({ kind: "error", message: requestError instanceof Error ? requestError.message : "No se pudo completar la conexión con Google." });
      }
    })();
  }, [params, router]);

  if (outcome.kind === "working") return <p className="rounded-xl border border-zinc-200 bg-white p-6 text-sm text-zinc-600">Conectando con Google...</p>;
  return (
    <div role="alert" className="max-w-xl rounded-xl border border-red-200 bg-red-50 p-6 text-sm text-red-800">
      <p className="font-semibold">{outcome.message}</p>
      <div className="mt-4 flex flex-wrap gap-4 font-bold">
        {outcome.offerRegister ? <Link href="/register" className="rounded-lg bg-red-800 px-4 py-2 text-white hover:bg-red-900">Crear mi cuenta</Link> : null}
        <Link href="/login" className="underline">Volver a iniciar sesión</Link>
      </div>
    </div>
  );
}
