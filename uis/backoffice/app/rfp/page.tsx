import { AuthGuard } from "@/components/auth-guard";
import { RfpIntake } from "@/components/rfp-intake";

export default function RfpPage() {
  return (
    <AuthGuard>
      <main>
        <RfpIntake />
      </main>
    </AuthGuard>
  );
}
