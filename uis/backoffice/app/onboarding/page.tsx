import { AuthGuard } from "@/components/auth-guard";
import { OnboardingPanel } from "@/components/onboarding-panel";

export default function OnboardingPage() {
  return (
    <AuthGuard>
      <main>
        <OnboardingPanel />
      </main>
    </AuthGuard>
  );
}
