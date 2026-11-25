import { AuthGuard } from "@/components/auth-guard";
import { SupplierContractsPanel } from "@/components/supplier-contracts-panel";

export default function SupplierContractsPage() {
  return (
    <AuthGuard>
      <main>
        <SupplierContractsPanel />
      </main>
    </AuthGuard>
  );
}
