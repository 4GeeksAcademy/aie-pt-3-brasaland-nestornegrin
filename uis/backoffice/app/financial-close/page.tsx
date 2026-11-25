import { AuthGuard } from "@/components/auth-guard";
import { FinancialClosePanel } from "@/components/financial-close-panel";

export default function FinancialClosePage() {
  return (
    <AuthGuard>
      <main>
        <FinancialClosePanel />
      </main>
    </AuthGuard>
  );
}
