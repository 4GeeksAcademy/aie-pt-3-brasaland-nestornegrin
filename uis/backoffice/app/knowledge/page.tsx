import { AuthGuard } from "@/components/auth-guard";
import { KnowledgeQueryForm } from "@/components/knowledge-query-form";

export default function KnowledgePage() {
  return (
    <AuthGuard>
      <main>
        <KnowledgeQueryForm />
      </main>
    </AuthGuard>
  );
}
