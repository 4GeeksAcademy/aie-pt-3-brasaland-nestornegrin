import { AuthGuard } from "@/components/auth-guard";
import { LinkedAccountsPanel } from "@/components/linked-accounts";
import { ProfileForm } from "@/components/profile-form";

export default function ProfilePage() {
  return <AuthGuard><main><ProfileForm /><LinkedAccountsPanel /></main></AuthGuard>;
}
