import React, { useState, useRef, useEffect } from "react";
import { PhoneOff, Mic, MicOff, Camera, Loader2, Sparkles, User, Image as ImageIcon, Volume2, Phone, AlertCircle, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useVoiceCall } from "@/hooks/useVoiceCall";

interface VoiceCallModalProps {
  isOpen: boolean;
  onClose: () => void;
  backendUrl?: string;
}

export function VoiceCallModal({ isOpen, onClose, backendUrl }: VoiceCallModalProps) {
  const {
    callStatus,
    aiStatus,
    userTranscription,
    aiTranscription,
    isMuted,
    errorMessage,
    startCall,
    endCall,
    toggleMute,
    uploadImage,
  } = useVoiceCall({ backendUrl });

  const [imageUrl, setImageUrl] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Full conversation transcript accumulated across all turns
  const [messages, setMessages] = useState<{ role: "user" | "ai"; text: string }[]>([]);
  const transcriptEndRef = useRef<HTMLDivElement>(null);

  // Append or update user message when transcription changes
  useEffect(() => {
    if (userTranscription) {
      setMessages((prev) => {
        const newMessages = [...prev];
        if (newMessages.length > 0 && newMessages[newMessages.length - 1].role === "user") {
          newMessages[newMessages.length - 1].text = userTranscription;
        } else {
          newMessages.push({ role: "user", text: userTranscription });
        }
        return newMessages;
      });
    }
  }, [userTranscription]);

  // Append or update AI message when AI transcription changes
  useEffect(() => {
    if (aiTranscription) {
      setMessages((prev) => {
        const newMessages = [...prev];
        if (newMessages.length > 0 && newMessages[newMessages.length - 1].role === "ai") {
          newMessages[newMessages.length - 1].text = aiTranscription;
        } else {
          newMessages.push({ role: "ai", text: aiTranscription });
        }
        return newMessages;
      });
    }
  }, [aiTranscription]);

  // Auto-scroll to bottom on new message
  useEffect(() => {
    transcriptEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Clean up resources when modal closes — do NOT auto-start on open
  useEffect(() => {
    if (!isOpen) {
      endCall();
      setImageUrl(null);
      setMessages([]);
    }
  }, [isOpen, endCall]);

  // End call AND close the modal
  const handleEndCall = () => {
    endCall();
    onClose();
  };

  const handleImageChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      const reader = new FileReader();
      reader.onloadend = () => {
        const base64 = reader.result as string;
        setImageUrl(base64);
        uploadImage(base64);
      };
      reader.readAsDataURL(file);
    }
  };

  const triggerFileInput = () => {
    fileInputRef.current?.click();
  };

  if (!isOpen) return null;

  // ── Status text & avatar animation ──
  let statusText = "Nhấn 'Bắt đầu' để kết nối với Bác sĩ AI";
  let avatarAnimationClass = "";

  if (callStatus === "connecting") {
    statusText = "Đang kết nối tới máy chủ...";
  } else if (callStatus === "connected") {
    switch (aiStatus) {
      case "idle":
        statusText = isMuted ? "Đã tắt mic - Cuộc gọi tạm dừng" : "Đang lắng nghe... Hãy bắt đầu nói";
        break;
      case "transcribing":
        statusText = "Đang xử lý giọng nói...";
        break;
      case "thinking":
        statusText = "Bác sĩ AI đang phân tích...";
        avatarAnimationClass = "animate-pulse shadow-[0_0_20px_rgba(59,130,246,0.5)]";
        break;
      case "speaking":
        statusText = "Bác sĩ AI đang trả lời...";
        avatarAnimationClass = "shadow-[0_0_30px_rgba(16,185,129,0.6)] ring-4 ring-emerald-400/30 animate-pulse";
        break;
    }
  } else if (callStatus === "error") {
    statusText = errorMessage || "Lỗi kết nối. Vui lòng thử lại.";
  } else if (callStatus === "disconnected") {
    statusText = "Cuộc gọi đã kết thúc.";
  }

  const isCallActive = callStatus === "connected" || callStatus === "connecting";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 backdrop-blur-md p-4 transition-all duration-300">
      <div className="relative flex flex-col w-full max-w-lg h-[90vh] max-h-[700px] bg-slate-900/90 text-white rounded-3xl border border-slate-800 shadow-2xl overflow-hidden">

        {/* Decorative background light */}
        <div className="absolute -top-40 -left-40 w-80 h-80 rounded-full bg-blue-500/10 blur-3xl" />
        <div className="absolute -bottom-40 -right-40 w-80 h-80 rounded-full bg-emerald-500/10 blur-3xl" />

        {/* Top Header */}
        <div className="flex items-center justify-between px-6 py-5 border-b border-slate-800/60 z-10">
          <div className="flex items-center gap-2">
            <Sparkles className="h-5 w-5 text-emerald-400 animate-spin" style={{ animationDuration: "4s" }} />
            <span className="font-semibold text-sm tracking-wide text-slate-300">CUỘC GỌI TƯ VẤN SINH LÝ 1-1</span>
          </div>
          <div className="flex items-center gap-2">
            <span className={`h-2.5 w-2.5 rounded-full ${
              callStatus === "connected" ? "bg-emerald-500 animate-ping" :
              callStatus === "connecting" ? "bg-amber-400 animate-pulse" :
              callStatus === "error" ? "bg-red-500" : "bg-slate-600"
            }`} />
            <span className="text-xs text-slate-400 font-medium">
              {callStatus === "connected" ? "TRỰC TUYẾN" :
               callStatus === "connecting" ? "ĐANG NỐI MÁY" :
               callStatus === "error" ? "LỖI KẾT NỐI" : "SẴN SÀNG"}
            </span>
          </div>
        </div>

        {/* Mid Area: Avatar & Status */}
        <div className="flex-1 flex flex-col items-center justify-center p-6 z-10">
          <div className="relative flex items-center justify-center mb-8">

            {/* Visual audio wave ripples when speaking */}
            {aiStatus === "speaking" && (
              <>
                <div className="absolute w-44 h-44 rounded-full bg-emerald-500/20 animate-ping" />
                <div className="absolute w-36 h-36 rounded-full bg-emerald-500/10 animate-pulse" />
              </>
            )}

            {aiStatus === "thinking" && (
              <div className="absolute w-40 h-40 rounded-full bg-blue-500/20 animate-spin border-2 border-dashed border-blue-400/30" />
            )}

            {callStatus === "connecting" && (
              <div className="absolute w-40 h-40 rounded-full border-2 border-dashed border-amber-400/40 animate-spin" />
            )}

            {/* Main Avatar */}
            <div className={`relative flex items-center justify-center w-28 h-28 rounded-full bg-gradient-to-br from-slate-800 to-slate-900 border-2 border-slate-700 overflow-hidden transition-all duration-500 ${avatarAnimationClass}`}>
              {callStatus === "error" ? (
                <AlertCircle className="h-12 w-12 text-red-400" />
              ) : callStatus === "connecting" ? (
                <Loader2 className="h-12 w-12 text-amber-400 animate-spin" />
              ) : aiStatus === "speaking" ? (
                <Volume2 className="h-12 w-12 text-emerald-400" />
              ) : aiStatus === "thinking" ? (
                <Loader2 className="h-12 w-12 text-blue-400 animate-spin" />
              ) : (
                <User className="h-12 w-12 text-slate-400" />
              )}
            </div>
          </div>

          <h3 className="text-lg font-semibold text-slate-100 mb-1">Bác sĩ Tư vấn Sức khỏe Sinh sản</h3>
          <p className={`text-sm font-medium text-center max-w-xs ${
            aiStatus === "speaking" ? "text-emerald-400" :
            aiStatus === "thinking" ? "text-blue-400" :
            callStatus === "error" ? "text-red-400" :
            callStatus === "connecting" ? "text-amber-400" :
            "text-slate-400"
          } transition-all`}>
            {statusText}
          </p>

          {/* Uploaded Image Preview */}
          {imageUrl && (
            <div className="relative mt-4 group">
              <img
                src={imageUrl}
                alt="Symptom preview"
                className="w-20 h-20 object-cover rounded-xl border border-slate-700 shadow-md transition hover:scale-105"
              />
              <span className="absolute -top-2 -right-2 bg-emerald-500 text-white rounded-full p-0.5 shadow">
                <ImageIcon className="h-3 w-3" />
              </span>
            </div>
          )}

          {/* Start / Retry button — only visible when call is NOT active */}
          {!isCallActive && (
            <Button
              onClick={startCall}
              className="mt-6 flex items-center gap-2 px-6 py-3 rounded-full bg-emerald-600 hover:bg-emerald-500 text-white font-semibold shadow-lg transition transform hover:scale-105 active:scale-95"
            >
              {callStatus === "error" ? (
                <><RefreshCw className="h-5 w-5" /> Thử lại</>
              ) : (
                <><Phone className="h-5 w-5" /> Bắt đầu cuộc gọi</>
              )}
            </Button>
          )}
        </div>

        {/* Live Conversation Transcript */}
        <div className="px-4 py-3 bg-slate-950/40 border-t border-slate-800/40 min-h-[130px] max-h-[200px] overflow-y-auto flex flex-col gap-2 text-sm z-10">
          {messages.length === 0 ? (
            <div className="text-center text-slate-500 py-4 italic">
              Lời thoại trò chuyện trực tiếp sẽ xuất hiện ở đây...
            </div>
          ) : (
            messages.map((msg, i) => (
              <div key={i} className={`flex gap-2 ${
                msg.role === "user" ? "justify-end" : "justify-start"
              }`}>
                {msg.role === "ai" && (
                  <span className="text-emerald-400 font-bold shrink-0 mt-0.5">BS:</span>
                )}
                <p className={`max-w-[80%] rounded-xl px-3 py-1.5 leading-relaxed ${
                  msg.role === "user"
                    ? "bg-amber-500/15 text-amber-100 italic text-right"
                    : "bg-slate-800 text-slate-200"
                }`}>
                  {msg.text}
                </p>
                {msg.role === "user" && (
                  <span className="text-amber-400 font-bold shrink-0 mt-0.5">Bạn</span>
                )}
              </div>
            ))
          )}
          {/* Anchor for auto-scroll */}
          <div ref={transcriptEndRef} />
        </div>

        {/* Hidden File Input */}
        <input
          type="file"
          ref={fileInputRef}
          onChange={handleImageChange}
          accept="image/*"
          className="hidden"
        />

        {/* Controls Footer */}
        <div className="flex items-center justify-center gap-6 px-6 py-7 border-t border-slate-800 bg-slate-950/80 z-10">

          {/* Mute Button */}
          <Button
            onClick={toggleMute}
            disabled={callStatus !== "connected"}
            variant="ghost"
            className={`w-12 h-12 rounded-full flex items-center justify-center p-0 border border-slate-800 transition disabled:opacity-40 ${
              isMuted
                ? "bg-amber-500/20 text-amber-400 border-amber-500/40 hover:bg-amber-500/30"
                : "bg-slate-800 text-slate-300 hover:bg-slate-700"
            }`}
          >
            {isMuted ? <MicOff className="h-5 w-5" /> : <Mic className="h-5 w-5" />}
          </Button>

          {/* End Call / Close Button */}
          <Button
            onClick={handleEndCall}
            className="w-16 h-16 rounded-full bg-red-600 hover:bg-red-500 text-white shadow-lg flex items-center justify-center p-0 transition transform hover:scale-105 active:scale-95"
          >
            <PhoneOff className="h-7 w-7" />
          </Button>

          {/* Image/Camera Upload for VLM */}
          <Button
            onClick={triggerFileInput}
            disabled={callStatus !== "connected"}
            variant="ghost"
            className="w-12 h-12 rounded-full bg-slate-800 text-slate-300 hover:bg-slate-700 border border-slate-800 flex items-center justify-center p-0 transition disabled:opacity-40"
            title="Chụp/Gửi ảnh bệnh lý cận cảnh"
          >
            <Camera className="h-5 w-5" />
          </Button>
        </div>
      </div>
    </div>
  );
}
