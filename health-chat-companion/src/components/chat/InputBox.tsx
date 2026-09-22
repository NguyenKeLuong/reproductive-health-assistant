import { useEffect, useRef, useState, KeyboardEvent } from "react";
import { Send, Square, Paperclip, X } from "lucide-react";
import { cn } from "@/lib/utils";

interface InputBoxProps {
  onSend: (text: string, image?: string) => void;
  disabled?: boolean;
  placeholder?: string;
}

export function InputBox({ onSend, disabled, placeholder }: InputBoxProps) {
  const [value, setValue] = useState("");
  const [image, setImage] = useState<string | null>(null);
  const taRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Auto-grow
  useEffect(() => {
    const ta = taRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = Math.min(ta.scrollHeight, 200) + "px";
  }, [value]);

  const submit = () => {
    const trimmed = value.trim();
    if ((!trimmed && !image) || disabled) return;
    onSend(trimmed, image || undefined);
    setValue("");
    setImage(null);
  };

  const handleKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      const reader = new FileReader();
      reader.onload = (event) => {
        const img = new Image();
        img.onload = () => {
          const canvas = document.createElement("canvas");
          let width = img.width;
          let height = img.height;
          
          // Limit max dimension to 800px for VLM clinical view
          const MAX_DIM = 800;
          if (width > MAX_DIM || height > MAX_DIM) {
            if (width > height) {
              height = Math.round((height * MAX_DIM) / width);
              width = MAX_DIM;
            } else {
              width = Math.round((width * MAX_DIM) / height);
              height = MAX_DIM;
            }
          }
          
          canvas.width = width;
          canvas.height = height;
          const ctx = canvas.getContext("2d");
          if (ctx) {
            ctx.drawImage(img, 0, 0, width, height);
            // Export to JPEG with 0.8 quality to keep payload < 100KB
            const dataUrl = canvas.toDataURL("image/jpeg", 0.8);
            setImage(dataUrl);
          } else {
            setImage(event.target?.result as string);
          }
        };
        img.src = event.target?.result as string;
      };
      reader.readAsDataURL(file);
    }
  };

  const triggerFileInput = () => {
    fileInputRef.current?.click();
  };

  const clearImage = () => {
    setImage(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  };

  return (
    <div className="px-3 sm:px-6 pb-4 pt-2 bg-gradient-to-t from-background via-background to-background/0">
      <div className="mx-auto max-w-3xl">
        
        {/* Image Preview Area */}
        {image && (
          <div className="relative inline-block mb-2 group">
            <img
              src={image}
              alt="Symptom attachment"
              className="w-16 h-16 object-cover rounded-xl border border-border shadow-soft"
            />
            <button
              onClick={clearImage}
              className="absolute -top-1.5 -right-1.5 bg-destructive text-destructive-foreground hover:bg-destructive/90 rounded-full p-0.5 shadow-md transition"
              title="Xóa hình ảnh"
            >
              <X className="h-3 w-3" />
            </button>
          </div>
        )}

        <div
          className={cn(
            "relative flex items-end gap-2 rounded-2xl border border-border bg-card p-2 shadow-soft transition-smooth",
            "focus-within:border-primary/50 focus-within:shadow-glow"
          )}
        >
          {/* File Input */}
          <input
            type="file"
            ref={fileInputRef}
            onChange={handleFileChange}
            accept="image/*"
            className="hidden"
          />

          {/* Attachment Button */}
          <button
            onClick={triggerFileInput}
            disabled={disabled}
            type="button"
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl text-muted-foreground hover:text-primary hover:bg-accent/50 transition-smooth"
            title="Đính kèm ảnh triệu chứng sinh lý"
          >
            <Paperclip className="h-4.5 w-4.5" />
          </button>

          {/* Text Input */}
          <textarea
            ref={taRef}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={handleKey}
            disabled={disabled}
            rows={1}
            placeholder={placeholder ?? "Hỏi hoặc đính kèm ảnh triệu chứng giới tính cận cảnh…"}
            className={cn(
              "flex-1 resize-none bg-transparent px-2 py-2 text-[15px] leading-relaxed",
              "placeholder:text-muted-foreground focus:outline-none",
              "max-h-[200px] scrollbar-thin",
              disabled && "opacity-60 cursor-not-allowed"
            )}
          />

          {/* Send Button */}
          <button
            onClick={submit}
            disabled={disabled || (!value.trim() && !image)}
            aria-label="Gửi"
            className={cn(
              "flex h-9 w-9 shrink-0 items-center justify-center rounded-xl transition-smooth",
              "bg-gradient-primary text-primary-foreground shadow-soft",
              "hover:shadow-glow disabled:opacity-40 disabled:cursor-not-allowed disabled:shadow-none"
            )}
          >
            {disabled ? <Square className="h-4 w-4" fill="currentColor" /> : <Send className="h-4 w-4" />}
          </button>
        </div>
        <p className="mt-2 text-center text-[11px] text-muted-foreground">
          Thông tin chỉ mang tính tham khảo, không thay thế tư vấn y tế chuyên môn.
        </p>
      </div>
    </div>
  );
}
