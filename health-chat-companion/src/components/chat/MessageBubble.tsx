import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Heart, User } from "lucide-react";
import { Message } from "@/types/chat";
import { cn } from "@/lib/utils";

interface MessageBubbleProps {
  message: Message;
  isStreaming?: boolean;
}

export function MessageBubble({ message, isStreaming }: MessageBubbleProps) {
  const isUser = message.role === "user";

  return (
    <div
      className={cn(
        "flex w-full gap-3 animate-fade-in-up",
        isUser ? "justify-end" : "justify-start"
      )}
    >
      {!isUser && (
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gradient-primary shadow-soft">
          <Heart className="h-4 w-4 text-primary-foreground" fill="currentColor" />
        </div>
      )}

      <div
        className={cn(
          "max-w-[85%] sm:max-w-[75%] rounded-2xl px-4 py-2.5 shadow-bubble prose-chat",
          isUser
            ? "user-bubble bg-user-bubble text-user-bubble-foreground rounded-tr-sm"
            : "bg-assistant-bubble text-assistant-bubble-foreground rounded-tl-sm border border-border/50"
        )}
      >
        {message.image && (
          <div className="mb-2">
            <img 
              src={message.image} 
              alt="Uploaded symptom" 
              className="max-w-[240px] max-h-[180px] object-cover rounded-xl border border-white/20 shadow-soft"
            />
          </div>
        )}
        {message.content ? (
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
        ) : isStreaming ? (
          <span className="inline-flex items-center gap-1 py-1 text-muted-foreground">
            <span className="typing-dot" />
            <span className="typing-dot" />
            <span className="typing-dot" />
          </span>
        ) : null}
        {isStreaming && message.content && (
          <span className="inline-block w-1.5 h-4 ml-0.5 align-middle bg-current opacity-60 animate-pulse" />
        )}
      </div>

      {isUser && (
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-secondary text-secondary-foreground shadow-soft">
          <User className="h-4 w-4" />
        </div>
      )}
    </div>
  );
}
