import { ForgotPasswordForm } from "@/components/forgot-password-form";

export default function ForgotPasswordPage() {
  return (
    <main className="mx-auto max-w-md">
      <h1 className="mb-6 text-3xl font-black">¿Olvidaste tu contraseña?</h1>
      <ForgotPasswordForm />
    </main>
  );
}
