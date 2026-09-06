import { AuthGuard } from "@/components/auth-guard";
import { ProfileForm } from "@/components/profile-form";

export default function ProfilePage() {
  return <AuthGuard><main><ProfileForm /></main></AuthGuard>;
}