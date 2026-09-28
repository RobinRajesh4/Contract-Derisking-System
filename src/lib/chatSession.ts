/**
 * Chat conversation state that outlives the Chat page.
 *
 * Answers can take minutes on the shared AI server. If the user opens a
 * contract ("View") or another page meanwhile, the Chat component
 * unmounts and a reply delivered through React state would be dropped,
 * leaving the question unanswered in the saved history. The request is
 * therefore owned here: the reply is written to the saved conversation
 * whether or not the page is open, and a re-mounted page picks it up.
 */
import { errorMessage, getBaseUrl } from "@/services/api";

export interface ChatSource {
  source_number?: number;
  analysis_id?: string;
  filename?: string;
  clause_id?: string | number;
  text: string;
  score?: number | null;
  kind?: "header" | "clause";
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  sources?: ChatSource[];
  coverage?: string;
}

const MESSAGES_KEY = "contract-chat-messages";
const MAX_SAVED_MESSAGES = 60;
const MAX_SAVED_SOURCE_TEXT = 600;

export const WELCOME: ChatMessage = {
  role: "assistant",
  content:
    "Hello! I can answer questions about the contracts you've uploaded. " +
    "Pick a contract at the top to ask about just that one, or keep \"All contracts\". What would you like to know?",
};

export function loadMessages(): ChatMessage[] {
  try {
    const saved = sessionStorage.getItem(MESSAGES_KEY);
    if (saved) {
      const parsed = JSON.parse(saved);
      if (Array.isArray(parsed) && parsed.length) return parsed as ChatMessage[];
    }
  } catch {
    try {
      sessionStorage.removeItem(MESSAGES_KEY);
    } catch {
      /* storage unavailable */
    }
  }
  return [WELCOME];
}

/**
 * Save, keeping it small: recent messages only, long source texts cut.
 * Browser storage is ~5 MB and a full store throws; that must never
 * take the page down, so failures are ignored (the conversation just
 * isn't restored after a reload).
 */
export function saveMessages(messages: ChatMessage[]): void {
  const trimmed = messages.slice(-MAX_SAVED_MESSAGES).map((m) =>
    m.sources
      ? {
          ...m,
          sources: m.sources.map((s) => ({
            ...s,
            text: s.text && s.text.length > MAX_SAVED_SOURCE_TEXT ? s.text.slice(0, MAX_SAVED_SOURCE_TEXT) + " …" : s.text,
          })),
        }
      : m
  );
  try {
    sessionStorage.setItem(MESSAGES_KEY, JSON.stringify(trimmed));
  } catch {
    try {
      sessionStorage.setItem(MESSAGES_KEY, JSON.stringify(trimmed.slice(-10)));
    } catch {
      /* storage full or unavailable */
    }
  }
}

type Listener = (messages: ChatMessage[], pending: boolean) => void;
let pending: Promise<void> | null = null;
let current: ChatMessage[] | null = null;
const listeners = new Set<Listener>();

/** The conversation (loaded from storage once, then kept in memory). */
export function getMessages(): ChatMessage[] {
  if (!current) current = loadMessages();
  return current;
}

export function isPending(): boolean {
  return pending !== null;
}

export function subscribe(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function publish(messages: ChatMessage[]) {
  current = messages;
  saveMessages(messages);
  listeners.forEach((l) => l(messages, pending !== null));
}

/**
 * Ask a question. `analysisId` limits the question to one contract
 * (null = all contracts). The user's message and the reply are appended
 * to the saved conversation and pushed to any open Chat page.
 */
export function ask(question: string, analysisId: string | null): Promise<void> {
  if (pending) return pending;
  const before = getMessages();
  const history = before
    .filter(
      (m) =>
        m.content &&
        m.content.trim() &&
        m.content !== WELCOME.content &&
        !m.content.startsWith("Sorry, I couldn't answer that.")
    )
    .slice(-8)
    .map((m) => ({ role: m.role, content: m.content.slice(0, 2000) }));
  const withQuestion: ChatMessage[] = [...before, { role: "user", content: question }];

  pending = (async () => {
    let reply: ChatMessage;
    try {
      const body: Record<string, unknown> = { message: question, top_k: 5, history };
      if (analysisId) body.analysis_id = analysisId;
      const response = await fetch(`${getBaseUrl()}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!response.ok) throw new Error(await errorMessage(response));
      const data = await response.json();
      reply = {
        role: "assistant",
        content: data.reply || "The AI returned an empty response.",
        sources: data.sources || [],
        coverage: data.coverage || undefined,
      };
    } catch (error) {
      const message = error instanceof Error ? error.message : "Unknown connection error";
      reply = {
        role: "assistant",
        content: `Sorry, I couldn't answer that. ${message}`,
      };
    }
    pending = null;
    publish([...getMessages(), reply]);
  })();

  publish(withQuestion);
  return pending;
}

export function clearConversation(): void {
  publish([WELCOME]);
}
