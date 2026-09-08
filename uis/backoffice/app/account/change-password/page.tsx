import { AuthGuard } from "@/components/auth-guard";
import { ChangePasswordForm } from "@/components/change-password-form";

export default function ChangePasswordPage() {
  return (
    <AuthGuard>
      <main>
        <ChangePasswordForm />
      </main>
    </AuthGuard>
  );
}
