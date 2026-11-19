import { AuthGuard } from "@/components/auth-guard";
import { ChatLive } from "@/components/chat-live";

export default function ChatPage() {
  return (
    <AuthGuard>
      <main>
        <ChatLive />
      </main>
    </AuthGuard>
  );
}
