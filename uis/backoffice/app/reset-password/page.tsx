import { Suspense } from "react";
import { ResetPasswordForm } from "@/components/reset-password-form";

export default function ResetPasswordPage() {
  return (
    <main className="mx-auto max-w-md">
      <h1 className="mb-6 text-3xl font-black">Restablecer contraseña</h1>
      <Suspense fallback={<p className="text-sm text-zinc-600">Cargando...</p>}>
        <ResetPasswordForm />
      </Suspense>
    </main>
  );
}
