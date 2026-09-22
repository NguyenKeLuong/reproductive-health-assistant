import { useEffect, useRef, useState, useCallback } from "react";
import { HistoryItem, WSIncoming } from "@/types/chat";

const getWsUrl = () => {
  const envUrl = import.meta.env.VITE_BACKEND_URL;
  if (envUrl) {
    // Convert http(s) to ws(s) and ensure it ends with /ws/chat
    let url = envUrl.replace(/^http/, "ws");
    if (!url.endsWith("/ws/chat")) {
      url = url.replace(/\/$/, "") + "/ws/chat";
    }
    return url;
  }
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/ws/chat`;
};

const WS_URL = getWsUrl();
const RECONNECT_DELAY = 2000;

export type WSStatus = "connecting" | "open" | "closed" | "error";

interface SendPayload {
  message: string;
  history: HistoryItem[];
  image?: string;
}

interface UseChatSocketOptions {
  onInfo?: (msg?: string) => void;
  onToken?: (chunk: string) => void;
  onDone?: (full: string) => void;
  onError?: (msg?: string) => void;
}

export function useChatSocket(opts: UseChatSocketOptions) {
  const [status, setStatus] = useState<WSStatus>("connecting");
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<number | null>(null);
  const shouldReconnect = useRef(true);
  const optsRef = useRef(opts);
  optsRef.current = opts;

  const connect = useCallback(() => {
    try {
      setStatus("connecting");
      const ws = new WebSocket(WS_URL);
      wsRef.current = ws;

      ws.onopen = () => setStatus("open");

      ws.onmessage = (ev) => {
        try {
          const data: WSIncoming = JSON.parse(ev.data);
          switch (data.type) {
            case "info":
              optsRef.current.onInfo?.(data.message);
              break;
            case "token":
              optsRef.current.onToken?.(data.content ?? "");
              break;
            case "done":
              optsRef.current.onDone?.(data.content ?? "");
              break;
            case "error":
              optsRef.current.onError?.(data.message);
              break;
          }
        } catch {
          /* ignore malformed */
        }
      };

      ws.onerror = () => setStatus("error");

      ws.onclose = () => {
        setStatus("closed");
        wsRef.current = null;
        if (shouldReconnect.current) {
          reconnectTimer.current = window.setTimeout(connect, RECONNECT_DELAY);
        }
      };
    } catch {
      setStatus("error");
      if (shouldReconnect.current) {
        reconnectTimer.current = window.setTimeout(connect, RECONNECT_DELAY);
      }
    }
  }, []);

  useEffect(() => {
    shouldReconnect.current = true;
    connect();
    return () => {
      shouldReconnect.current = false;
      if (reconnectTimer.current) window.clearTimeout(reconnectTimer.current);
      wsRef.current?.close();
    };
  }, [connect]);

  const send = useCallback((payload: SendPayload): boolean => {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) return false;
    ws.send(JSON.stringify(payload));
    return true;
  }, []);

  return { status, send };
}
