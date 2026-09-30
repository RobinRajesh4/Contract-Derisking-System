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
  /** Other contracts with identical wording for this passage. */
  also_in?: { analysis_id: string; filename: string }[];
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  sources?: ChatSource[];
  coverage?: string;
  /** "structured" = computed exactly from contract data; "semantic" = written by the model. */
  route?: string;
  /** Model that wrote the answer (null for exact answers). */
  model?: string | null;
  /** Model that interpreted the question. */
  routerModel?: string | null;
  /** "inferred": the answer cited nothing inline; the references are the
   *  passages it most likely drew on. */
  citations?: "cited" | "inferred" | "none";
  /** The exact query behind a computed answer; sent back with the next
   *  question so "list the other ones too" can widen it. */
  querySpec?: Record<string, unknown> | null;
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

/** The answer being written right now (not saved until it's finished). */
export interface LiveAnswer {
  text: string;
  /** What the server is doing before the first words arrive. */
  status?: string;
  model?: string | null;
}

type Listener = (messages: ChatMessage[], pending: boolean, live: LiveAnswer | null) => void;
let pending: Promise<void> | null = null;
let current: ChatMessage[] | null = null;
let live: LiveAnswer | null = null;
const listeners = new Set<Listener>();

export function getLive(): LiveAnswer | null {
  return live;
}

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
  listeners.forEach((l) => l(messages, pending !== null, live));
}

// Words can arrive dozens of times a second; redraw at most every 60 ms.
let liveTimer: ReturnType<typeof setTimeout> | null = null;
function publishLive() {
  if (liveTimer) return;
  liveTimer = setTimeout(() => {
    liveTimer = null;
    listeners.forEach((l) => l(getMessages(), pending !== null, live));
  }, 60);
}

function toReply(data: any): ChatMessage {
  return {
    role: "assistant",
    content: data.reply || "The AI returned an empty response.",
    sources: data.sources || [],
    coverage: data.coverage || undefined,
    route: data.route,
    model: data.model ?? null,
    routerModel: data.router_model ?? null,
    citations: data.citations,
    querySpec: data.route === "structured" ? data.query_spec ?? null : null,
  };
}

/**
 * The answer from /chat/stream, shown word by word as it's written.
 * Returns null if this backend has no streaming endpoint (older version),
 * so the caller can use /chat instead.
 */
async function askStreaming(body: Record<string, unknown>): Promise<ChatMessage | null> {
  const response = await fetch(`${getBaseUrl()}/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (response.status === 404 || response.status === 405) return null;
  if (!response.ok) throw new Error(await errorMessage(response));
  if (!response.body) return null;

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffered = "";
  let finished: ChatMessage | null = null;
  const handle = (line: string) => {
    if (!line.trim()) return;
    const event = JSON.parse(line);
    if (event.type === "status") live = { ...(live || { text: "" }), status: event.text };
    else if (event.type === "model") live = { ...(live || { text: "" }), model: event.model };
    else if (event.type === "delta") live = { ...(live || { text: "" }), text: (live?.text || "") + event.text, status: undefined };
    else if (event.type === "error") throw new Error(event.detail || "The answer failed.");
    else if (event.type === "done") finished = toReply(event);
    publishLive();
  };
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffered += decoder.decode(value, { stream: true });
    const lines = buffered.split("\n");
    buffered = lines.pop() || "";
    lines.forEach(handle);
  }
  handle(buffered);
  if (!finished) throw new Error("The connection closed before the answer was finished.");
  return finished;
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
  const lastAnswer = [...before].reverse().find((m) => m.role === "assistant" && m.content !== WELCOME.content);
  const previousSpec = lastAnswer?.route === "structured" ? lastAnswer.querySpec : null;
  const previousIds = previousSpec
    ? Array.from(new Set((lastAnswer?.sources || []).map((s) => s.analysis_id).filter(Boolean)))
    : [];
  const withQuestion: ChatMessage[] = [...before, { role: "user", content: question }];

  pending = (async () => {
    let reply: ChatMessage;
    try {
      const body: Record<string, unknown> = { message: question, top_k: 5, history };
      if (analysisId) body.analysis_id = analysisId;
      if (previousSpec) {
        body.previous_spec = previousSpec;
        body.previous_ids = previousIds;
      }
      const streamed = await askStreaming(body);
      if (streamed) {
        reply = streamed;
      } else {
        const response = await fetch(`${getBaseUrl()}/chat`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        if (!response.ok) throw new Error(await errorMessage(response));
        reply = toReply(await response.json());
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : "Unknown connection error";
      // Keep what was already written, so a half-finished answer isn't lost.
      const partial = live?.text?.trim();
      reply = {
        role: "assistant",
        content: partial
          ? `${partial}\n\n_The answer was cut off: ${message}_`
          : `Sorry, I couldn't answer that. ${message}`,
      };
    }
    pending = null;
    live = null;
    publish([...getMessages(), reply]);
  })();

  live = { text: "", status: "Sending the question" };
  publish(withQuestion);
  return pending;
}

export function clearConversation(): void {
  publish([WELCOME]);
}
