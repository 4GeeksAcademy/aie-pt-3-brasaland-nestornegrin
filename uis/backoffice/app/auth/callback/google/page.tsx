import { Suspense } from "react";
import { FederatedCallback } from "@/components/federated-callback";

export default function GoogleCallbackPage() {
  return <main><Suspense fallback={<p className="text-sm text-zinc-600">Conectando con Google...</p>}><FederatedCallback /></Suspense></main>;
}
