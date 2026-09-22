import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Menu, Wifi, WifiOff, Loader2, Phone } from "lucide-react";
import { Conversation, HistoryItem, Message } from "@/types/chat";
import {
  loadActiveId,
  loadConversations,
  saveActiveId,
  saveConversations,
} from "@/lib/storage";
import { useChatSocket } from "@/hooks/useChatSocket";
import { useTheme } from "@/hooks/useTheme";
import { Sidebar } from "@/components/chat/Sidebar";
import { ChatWindow } from "@/components/chat/ChatWindow";
import { InputBox } from "@/components/chat/InputBox";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent } from "@/components/ui/sheet";
import { useToast } from "@/hooks/use-toast";
import { cn } from "@/lib/utils";
import { VoiceCallModal } from "@/components/chat/VoiceCallModal";

const uid = () =>
  typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : Math.random().toString(36).slice(2) + Date.now().toString(36);


const titleFromMessage = (text: string) => {
  const t = text.trim().replace(/\s+/g, " ");
  return t.length > 48 ? t.slice(0, 48) + "…" : t || "Cuộc trò chuyện mới";
};

const Index = () => {
  const { theme, toggle: toggleTheme } = useTheme();
  const { toast } = useToast();

  const [conversations, setConversations] = useState<Conversation[]>(() =>
    loadConversations()
  );
  const [activeId, setActiveId] = useState<string | null>(() => {
    const stored = loadActiveId();
    const all = loadConversations();
    if (stored && all.find((c) => c.id === stored)) return stored;
    return all[0]?.id ?? null;
  });

  const [streamingId, setStreamingId] = useState<string | null>(null);
  const [isWaiting, setIsWaiting] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [isVoiceCallOpen, setIsVoiceCallOpen] = useState(false);

  // Persist
  useEffect(() => saveConversations(conversations), [conversations]);
  useEffect(() => saveActiveId(activeId), [activeId]);

  // Track which assistant message id we're filling — must persist across renders
  const pendingAssistantRef = useRef<string | null>(null);

  const updateConversation = useCallback(
    (id: string, updater: (c: Conversation) => Conversation) => {
      setConversations((prev) =>
        prev.map((c) => (c.id === id ? updater(c) : c))
      );
    },
    []
  );

  const appendToken = useCallback(
    (chunk: string) => {
      const convId = activeId;
      const msgId = pendingAssistantRef.current;
      if (!convId || !msgId) return;
      updateConversation(convId, (c) => ({
        ...c,
        updatedAt: Date.now(),
        messages: c.messages.map((m) =>
          m.id === msgId ? { ...m, content: m.content + chunk } : m
        ),
      }));
    },
    [activeId, updateConversation]
  );

  const finalizeAssistant = useCallback(
    (full?: string) => {
      const convId = activeId;
      const msgId = pendingAssistantRef.current;
      pendingAssistantRef.current = null;
      setStreamingId(null);
      setIsWaiting(false);
      if (!convId || !msgId) return;
      if (full && full.length > 0) {
        updateConversation(convId, (c) => ({
          ...c,
          updatedAt: Date.now(),
          messages: c.messages.map((m) =>
            m.id === msgId 
              ? { ...m, content: full.length > m.content.length ? full : m.content } 
              : m
          ),
        }));
      } else {
        // If empty, remove the placeholder only if it's still empty
        updateConversation(convId, (c) => ({
          ...c,
          messages: c.messages.filter(
            (m) => !(m.id === msgId && m.content.length === 0)
          ),
        }));
      }
    },
    [activeId, updateConversation]
  );

  const { status, send } = useChatSocket({
    onInfo: () => {
      // server is processing — keep typing indicator
    },
    onToken: (chunk) => {
      setIsWaiting(false);
      appendToken(chunk);
    },
    onDone: (full) => {
      finalizeAssistant(full);
    },
    onError: (msg) => {
      const convId = activeId;
      const msgId = pendingAssistantRef.current;
      pendingAssistantRef.current = null;
      setStreamingId(null);
      setIsWaiting(false);
      if (convId && msgId) {
        updateConversation(convId, (c) => ({
          ...c,
          messages: c.messages.filter((m) => m.id !== msgId || m.content.length > 0),
        }));
      }
      toast({
        variant: "destructive",
        title: "Lỗi từ máy chủ",
        description: msg ?? "Không thể nhận phản hồi. Vui lòng thử lại.",
      });
    },
  });

  const activeConversation = useMemo(
    () => conversations.find((c) => c.id === activeId) ?? null,
    [conversations, activeId]
  );

  const handleNewChat = useCallback(() => {
    const c: Conversation = {
      id: uid(),
      title: "Cuộc trò chuyện mới",
      messages: [],
      createdAt: Date.now(),
      updatedAt: Date.now(),
    };
    setConversations((prev) => [c, ...prev]);
    setActiveId(c.id);
    setSidebarOpen(false);
  }, []);

  const handleSelect = useCallback((id: string) => {
    setActiveId(id);
    setSidebarOpen(false);
  }, []);

  const handleDelete = useCallback(
    (id: string) => {
      setConversations((prev) => {
        const next = prev.filter((c) => c.id !== id);
        if (activeId === id) {
          setActiveId(next[0]?.id ?? null);
        }
        return next;
      });
    },
    [activeId]
  );

  const handleSend = useCallback(
    (text: string, image?: string) => {
      if (isWaiting || streamingId) return;

      if (status !== "open") {
        toast({
          variant: "destructive",
          title: "Mất kết nối",
          description:
            "Đang thử kết nối lại tới máy chủ. Vui lòng thử lại trong giây lát.",
        });
        return;
      }

      // Ensure we have a conversation
      let convId = activeId;
      let isNew = false;
      if (!convId) {
        const c: Conversation = {
          id: uid(),
          title: titleFromMessage(text || "Hình ảnh triệu chứng"),
          messages: [],
          createdAt: Date.now(),
          updatedAt: Date.now(),
        };
        convId = c.id;
        isNew = true;
        setConversations((prev) => [c, ...prev]);
        setActiveId(c.id);
      }

      const userMsg: Message = {
        id: uid(),
        role: "user",
        content: text,
        image: image,
        createdAt: Date.now(),
      };
      const assistantMsg: Message = {
        id: uid(),
        role: "assistant",
        content: "",
        createdAt: Date.now(),
      };

      // Build history from CURRENT state (messages prior to this turn)
      const existing =
        conversations.find((c) => c.id === convId)?.messages ?? [];
      const history: HistoryItem[] = existing.map((m) => ({
        role: m.role,
        content: m.content,
      }));

      // Optimistic add
      setConversations((prev) =>
        prev.map((c) =>
          c.id === convId
            ? {
                ...c,
                title:
                  c.messages.length === 0 || isNew
                    ? titleFromMessage(text || "Hình ảnh triệu chứng")
                    : c.title,
                messages: [...c.messages, userMsg, assistantMsg],
                updatedAt: Date.now(),
              }
            : c
        )
      );

      pendingAssistantRef.current = assistantMsg.id;
      setStreamingId(assistantMsg.id);
      setIsWaiting(true);

      const ok = send({ message: text, history, image });
      if (!ok) {
        pendingAssistantRef.current = null;
        setStreamingId(null);
        setIsWaiting(false);
        // remove placeholder assistant
        setConversations((prev) =>
          prev.map((c) =>
            c.id === convId
              ? { ...c, messages: c.messages.filter((m) => m.id !== assistantMsg.id) }
              : c
          )
        );
        toast({
          variant: "destructive",
          title: "Không gửi được",
          description: "Mất kết nối WebSocket. Đang thử kết nối lại…",
        });
      }
    },
    [
      activeId,
      conversations,
      isWaiting,
      send,
      status,
      streamingId,
      toast,
    ]
  );

  const inputDisabled = isWaiting || !!streamingId;

  return (
    <div className="flex h-dvh w-full overflow-hidden bg-gradient-subtle">
      {/* Desktop sidebar */}
      <div className="hidden md:flex w-[280px] shrink-0">
        <Sidebar
          conversations={conversations}
          activeId={activeId}
          onSelect={handleSelect}
          onNew={handleNewChat}
          onDelete={handleDelete}
          theme={theme}
          onToggleTheme={toggleTheme}
        />
      </div>

      {/* Mobile sidebar */}
      <Sheet open={sidebarOpen} onOpenChange={setSidebarOpen}>
        <SheetContent side="left" className="p-0 w-[300px] max-w-[85vw] border-r-0">
          <Sidebar
            conversations={conversations}
            activeId={activeId}
            onSelect={handleSelect}
            onNew={handleNewChat}
            onDelete={handleDelete}
            onClose={() => setSidebarOpen(false)}
            isMobile
            theme={theme}
            onToggleTheme={toggleTheme}
          />
        </SheetContent>
      </Sheet>

      {/* Main */}
      <main className="flex flex-1 flex-col min-w-0">
        {/* Top bar */}
        <header className="flex items-center justify-between gap-2 px-3 sm:px-6 h-14 border-b border-border bg-background/80 backdrop-blur">
          <div className="flex items-center gap-2 min-w-0">
            <Button
              variant="ghost"
              size="icon"
              className="md:hidden h-9 w-9"
              onClick={() => setSidebarOpen(true)}
              aria-label="Mở menu"
            >
              <Menu className="h-5 w-5" />
            </Button>
            <h2 className="font-display font-semibold text-sm sm:text-base truncate">
              {activeConversation?.title ?? "HealthChat"}
            </h2>
          </div>

          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="icon"
              onClick={() => setIsVoiceCallOpen(true)}
              className="h-9 w-9 rounded-full border-primary/20 hover:bg-primary/10 text-primary"
              title="Gọi điện tư vấn 1-1"
            >
              <Phone className="h-4 w-4" />
            </Button>
            <ConnectionBadge status={status} />
          </div>
        </header>

        {/* Chat area */}
        <ChatWindow
          conversation={activeConversation}
          streamingId={streamingId}
          onPickSuggestion={handleSend}
        />

        {/* Input */}
        <InputBox
          onSend={handleSend}
          disabled={inputDisabled}
          placeholder={
            inputDisabled
              ? "Trợ lý đang trả lời…"
              : "Hỏi điều bạn đang băn khoăn về sức khỏe giới tính…"
          }
        />
        <VoiceCallModal 
          isOpen={isVoiceCallOpen} 
          onClose={() => setIsVoiceCallOpen(false)} 
          backendUrl={import.meta.env.VITE_BACKEND_URL} 
        />
      </main>
    </div>
  );
};

function ConnectionBadge({
  status,
}: {
  status: "connecting" | "open" | "closed" | "error";
}) {
  const map = {
    open: {
      label: "Đã kết nối",
      icon: <Wifi className="h-3.5 w-3.5" />,
      cls: "text-primary bg-accent",
    },
    connecting: {
      label: "Đang kết nối",
      icon: <Loader2 className="h-3.5 w-3.5 animate-spin" />,
      cls: "text-muted-foreground bg-muted",
    },
    closed: {
      label: "Mất kết nối",
      icon: <WifiOff className="h-3.5 w-3.5" />,
      cls: "text-destructive bg-destructive/10",
    },
    error: {
      label: "Lỗi kết nối",
      icon: <WifiOff className="h-3.5 w-3.5" />,
      cls: "text-destructive bg-destructive/10",
    },
  }[status];

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-medium",
        map.cls
      )}
    >
      {map.icon}
      <span className="hidden sm:inline">{map.label}</span>
    </span>
  );
}

export default Index;
