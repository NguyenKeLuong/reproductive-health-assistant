export type Role = "user" | "assistant";

export interface Message {
  id: string;
  role: Role;
  content: string;
  image?: string;
  createdAt: number;
}

export interface Conversation {
  id: string;
  title: string;
  messages: Message[];
  createdAt: number;
  updatedAt: number;
}

export interface HistoryItem {
  role: Role;
  content: string;
}

export type WSIncoming =
  | { type: "info"; message?: string }
  | { type: "token"; content: string }
  | { type: "done"; content: string }
  | { type: "error"; message?: string };
