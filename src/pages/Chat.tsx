import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Bot,
  FileText,
  Send,
  User,
  BookOpen,
  ChevronRight,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { listAnalyses, getAnalysis } from "@/services/analysis";

/* ─── Types ──────────────────────────────────────────────── */

interface Source {
  source_number?: number;
  analysis_id?: string;
  clause_id?: string | number;
  text: string;
  score?: number;
}

interface Message {
  role: "user" | "assistant";
  content: string;
  sources?: Source[];
}


/**
 * Strip common Markdown syntax so it doesn't render as literal
 * asterisks/hashes in the plain-text chat bubble.
 */
function stripMarkdown(text: string): string {
  return text
    .replace(/^#{1,6}\s+/gm, "") // headers
    .replace(/\*\*\*(.+?)\*\*\*/g, "$1") // bold+italic
    .replace(/\*\*(.+?)\*\*/g, "$1") // bold
    .replace(/\*(.+?)\*/g, "$1") // italic
    .replace(/__(.+?)__/g, "$1") // bold (underscore)
    .replace(/_(.+?)_/g, "$1") // italic (underscore)
    .replace(/^\s*[-*+]\s+/gm, "\u2022 ") // bullet lists -> •
    .replace(/`{1,3}([^`]+)`{1,3}/g, "$1"); // inline/code fences
}

/* ─── Helpers ────────────────────────────────────────────── */

/**
 * Replace "[Source N]" markers inside reply text with styled
 * inline superscript spans so they visually match the source chips.
 */
function linkifySourceRefs(
  text: string,
  onClickRef: (n: number) => void
): React.ReactNode[] {
  const parts = text.split(/(\[Source \d+\])/g);
  return parts.map((part, i) => {
    const m = part.match(/\[Source (\d+)\]/);
    if (m) {
      const num = parseInt(m[1], 10);
      return (
        <button
          key={i}
          onClick={() => onClickRef(num)}
          className="mx-0.5 inline-flex h-4 w-4 items-center justify-center rounded-full bg-primary/20 text-[10px] font-bold text-primary ring-1 ring-primary/40 hover:bg-primary/40 transition-colors cursor-pointer align-super"
          title={`Jump to Source ${num}`}
        >
          {num}
        </button>
      );
    }
    return <span key={i}>{part}</span>;
  });
}

/* ─── Document Viewer ────────────────────────────────────── */

interface DocumentViewerProps {
  analysisId: string | null;
  highlightedClauseId: string | number | null;
}

function DocumentViewer({
  analysisId,
  highlightedClauseId,
}: DocumentViewerProps) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["analysis-clauses", analysisId],
    queryFn: () => getAnalysis(analysisId as string),
    enabled: !!analysisId,
  });

  const clauseRefs = useRef<Record<string | number, HTMLDivElement | null>>({});

  // Scroll to + flash the highlighted clause whenever it changes
  useEffect(() => {
    if (highlightedClauseId == null) return;

    const el = clauseRefs.current[highlightedClauseId];
    if (!el) return;

    // Remove old animation class so it can re-trigger
    el.classList.remove("clause-highlighted");
    // Force reflow to restart animation
    void el.offsetWidth;
    el.classList.add("clause-highlighted");

    el.scrollIntoView({ behavior: "smooth", block: "center" });

    const timer = setTimeout(() => {
      el.classList.remove("clause-highlighted");
    }, 3200);

    return () => clearTimeout(timer);
  }, [highlightedClauseId]);

  if (!analysisId) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-4 text-muted-foreground">
        <BookOpen className="h-12 w-12 opacity-30" />
        <div className="text-center">
          <p className="text-sm font-medium">No contract selected</p>
          <p className="mt-1 text-xs opacity-70">
            Select a specific contract from the dropdown to view the document
            and jump to referenced clauses.
          </p>
        </div>
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center text-muted-foreground">
        <div className="flex flex-col items-center gap-3">
          <div className="h-6 w-6 animate-spin rounded-full border-2 border-primary border-t-transparent" />
          <p className="text-xs">Loading document…</p>
        </div>
      </div>
    );
  }

  if (isError || !data) {
    return (
      <div className="flex h-full items-center justify-center text-destructive">
        <p className="text-sm">Failed to load document.</p>
      </div>
    );
  }

  const clauses: Array<{ id: string | number; text: string }> =
    data.clauses ?? data.results ?? [];

  const filename: string = data.filename ?? "Contract";

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Document header */}
      <div className="shrink-0 border-b bg-muted/50 px-5 py-3">
        <div className="flex items-center gap-2">
          <FileText className="h-4 w-4 text-primary" />
          <span className="truncate text-sm font-semibold">{filename}</span>
        </div>
        <p className="mt-0.5 text-xs text-muted-foreground">
          {clauses.length} clause{clauses.length !== 1 ? "s" : ""}
        </p>
      </div>

      {/* Clause list */}
      <div className="flex-1 overflow-y-auto p-5 space-y-4">
        {clauses.map((clause) => (
          <div
            key={clause.id}
            ref={(el) => {
              clauseRefs.current[clause.id] = el;
            }}
            data-clause-id={clause.id}
            className="group relative rounded-md border border-border/40 bg-background p-4 text-sm leading-relaxed transition-colors hover:border-border"
          >
            {/* Clause number badge */}
            <span className="mb-2 inline-block rounded bg-muted px-1.5 py-0.5 text-[10px] font-bold text-muted-foreground">
              §{clause.id}
            </span>
            <p className="whitespace-pre-wrap text-foreground/90">{clause.text}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ─── Main Chat Component ────────────────────────────────── */

export default function Chat() {
  /* ── State: messages ─── */
  const [messages, setMessages] = useState<Message[]>(() => {
    const saved = sessionStorage.getItem("contract-chat-messages");
    if (saved) {
      try {
        return JSON.parse(saved) as Message[];
      } catch {
        sessionStorage.removeItem("contract-chat-messages");
      }
    }
    return [
      {
        role: "assistant",
        content:
          "Hello! I can answer questions about contracts that have been uploaded and indexed. " +
          "Select a contract on the right or search across all contracts. What would you like to know?",
      },
    ];
  });

  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);

  /* ── State: contract selection ─── */
  const [selectedAnalysisId, setSelectedAnalysisId] = useState(
    () => sessionStorage.getItem("contract-chat-selected-analysis") || "all"
  );

  /* ── State: highlighted clause in document viewer ─── */
  const [highlightedClauseId, setHighlightedClauseId] = useState<
    string | number | null
  >(null);

  /* ── State: pane split width ─── */
  const [leftWidth, setLeftWidth] = useState(44); // percent
  const isDragging = useRef(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const dividerRef = useRef<HTMLDivElement>(null);

  /* ── Drag-to-resize logic ─── */
  const onMouseDownDivider = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      isDragging.current = true;
      dividerRef.current?.classList.add("dragging");

      const onMouseMove = (ev: MouseEvent) => {
        if (!isDragging.current || !containerRef.current) return;
        const rect = containerRef.current.getBoundingClientRect();
        const pct = ((ev.clientX - rect.left) / rect.width) * 100;
        setLeftWidth(Math.min(Math.max(pct, 25), 70));
      };

      const onMouseUp = () => {
        isDragging.current = false;
        dividerRef.current?.classList.remove("dragging");
        window.removeEventListener("mousemove", onMouseMove);
        window.removeEventListener("mouseup", onMouseUp);
      };

      window.addEventListener("mousemove", onMouseMove);
      window.addEventListener("mouseup", onMouseUp);
    },
    []
  );

  /* ── Persist session ─── */
  useEffect(() => {
    sessionStorage.setItem("contract-chat-selected-analysis", selectedAnalysisId);
  }, [selectedAnalysisId]);

  useEffect(() => {
    sessionStorage.setItem("contract-chat-messages", JSON.stringify(messages));
  }, [messages]);

  /* ── Fetch analyses list ─── */
  const {
    data: analysesData,
    isLoading: isLoadingAnalyses,
    isError: isAnalysesError,
  } = useQuery({
    queryKey: ["analyses"],
    queryFn: () => listAnalyses(),
  });

  const analyses = (analysesData as any[] | undefined) || [];

  const selectedAnalysis =
    selectedAnalysisId === "all"
      ? null
      : analyses.find((a: any) => a.analysis_id === selectedAnalysisId);

  /* ── Scroll messages to bottom ─── */
  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  /* ── Build a source-number → clause mapping from last assistant message ─── */
  const lastSourceMap = useMemo(() => {
    const map: Record<number, Source> = {};
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].role === "assistant" && messages[i].sources?.length) {
        for (const src of messages[i].sources!) {
          if (src.source_number != null) map[src.source_number] = src;
        }
        break;
      }
    }
    return map;
  }, [messages]);

  /* ── Jump-to-source handler ─── */
  const handleSourceClick = useCallback(
    (source: Source) => {
      // If a specific analysis is referenced, switch to it
      if (source.analysis_id && selectedAnalysisId !== source.analysis_id) {
        setSelectedAnalysisId(source.analysis_id);
      }
      if (source.clause_id != null) {
        // Slight delay to allow the doc viewer to load after analysis switch
        setTimeout(() => setHighlightedClauseId(source.clause_id!), 150);
      }
    },
    [selectedAnalysisId]
  );

  /* ── Send message ─── */
  const sendMessage = async () => {
    const question = input.trim();
    if (!question || isLoading) return;
    setInput("");
    setMessages((prev) => [...prev, { role: "user", content: question }]);
    setIsLoading(true);

    try {
      const requestBody: {
        message: string;
        top_k: number;
        analysis_id?: string;
      } = { message: question, top_k: 5 };

      if (selectedAnalysisId !== "all") {
        requestBody.analysis_id = selectedAnalysisId;
      }

      const response = await fetch("http://127.0.0.1:8001/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(requestBody),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || "Failed to get a response");
      }

      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: data.reply || "The AI returned an empty response.",
          sources: data.sources || [],
        },
      ]);
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "Unknown connection error";
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: `Sorry, the contract assistant could not complete the request. ${message}`,
        },
      ]);
    } finally {
      setIsLoading(false);
    }
  };

  /* ── Render ─── */
  return (
    <div className="flex h-[calc(100vh-8rem)] flex-col overflow-hidden rounded-xl border bg-background shadow-md">
      {/* ── Top bar ── */}
      <div className="shrink-0 border-b bg-muted/60 px-6 py-3">
        <div className="flex flex-wrap items-center gap-4">
          <div className="flex items-center gap-2">
            <Bot className="h-5 w-5 text-primary" />
            <h2 className="text-base font-semibold">Contract Chatbot</h2>
          </div>

          <div className="flex flex-1 items-center gap-2 text-sm text-muted-foreground">
            <ChevronRight className="h-3.5 w-3.5" />
            <div className="w-56">
              <Select
                value={selectedAnalysisId}
                onValueChange={setSelectedAnalysisId}
                disabled={isLoadingAnalyses}
              >
                <SelectTrigger className="h-8 text-xs">
                  <SelectValue placeholder="Select contract" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All Contracts</SelectItem>
                  {analyses.map((a: any) => (
                    <SelectItem key={a.analysis_id} value={a.analysis_id}>
                      {a.filename ||
                        `Analysis ${a.analysis_id?.slice(0, 8)}`}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {isLoadingAnalyses && (
              <span className="text-xs">Loading contracts…</span>
            )}
            {isAnalysesError && (
              <span className="text-xs text-destructive">
                Failed to load contracts.
              </span>
            )}
            {!isLoadingAnalyses && analyses.length > 0 && (
              <span className="text-xs opacity-60">
                {selectedAnalysisId === "all"
                  ? `${analyses.length} contracts`
                  : selectedAnalysis?.filename
                    ? selectedAnalysis.filename
                    : `Analysis ${selectedAnalysisId.slice(0, 8)}`}
              </span>
            )}
          </div>
        </div>
      </div>

      {/* ── Split panes ── */}
      <div ref={containerRef} className="flex flex-1 overflow-hidden">
        {/* LEFT: Chat */}
        <div
          className="flex flex-col overflow-hidden"
          style={{ width: `${leftWidth}%` }}
        >
          {/* Message list */}
          <div className="flex-1 space-y-5 overflow-y-auto p-5">
            {messages.map((message, index) => {
              const isBot = message.role === "assistant";
              return (
                <div
                  key={index}
                  className={`flex gap-3 ${isBot ? "" : "justify-end"}`}
                >
                  {isBot && (
                    <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary/10">
                      <Bot className="h-4 w-4 text-primary" />
                    </div>
                  )}

                  <div
                    className={`max-w-[85%] rounded-xl px-4 py-3 text-sm ${
                      isBot
                        ? "bg-muted text-foreground"
                        : "bg-primary text-primary-foreground"
                    }`}
                  >
                    {/* Message text with inline [Source N] refs linkified */}
                    <p className="whitespace-pre-wrap leading-relaxed">
                      {isBot
                        ? linkifySourceRefs(stripMarkdown(message.content), (n) => {
                            const src = lastSourceMap[n];
                            if (src) handleSourceClick(src);
                          })
                        : message.content}
                    </p>

                    {/* Source chips */}
                    {isBot &&
                      message.sources &&
                      message.sources.length > 0 && (
                        <div className="mt-3 border-t border-border/40 pt-3">
                          <p className="mb-2 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                            References
                          </p>
                          <div className="flex flex-col gap-1.5">
                            {message.sources.map((source, si) => (
                              <button
                                key={si}
                                onClick={() => handleSourceClick(source)}
                                className="group flex w-full items-start gap-2 rounded-lg border border-border/50 bg-background/60 p-2 text-left text-xs transition-all hover:border-primary/50 hover:bg-background hover:shadow-sm active:scale-[0.99]"
                                title="Click to jump to this clause in the document"
                              >
                                {/* Source number badge */}
                                <span className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-primary/15 text-[10px] font-bold text-primary ring-1 ring-primary/30 group-hover:bg-primary/25">
                                  {source.source_number ?? si + 1}
                                </span>

                                <div className="min-w-0 flex-1">
                                  <p className="line-clamp-2 leading-snug text-foreground/80">
                                    {source.text}
                                  </p>
                                  <div className="mt-1 flex flex-wrap gap-x-3 text-[10px] text-muted-foreground">
                                    {source.clause_id != null && (
                                      <span>Clause {source.clause_id}</span>
                                    )}
                                    {typeof source.score === "number" && (
                                      <span>
                                        Relevance {source.score.toFixed(2)}
                                      </span>
                                    )}
                                    <span className="font-medium text-primary group-hover:underline">
                                      Jump to clause →
                                    </span>
                                  </div>
                                </div>
                              </button>
                            ))}
                          </div>
                        </div>
                      )}
                  </div>

                  {!isBot && (
                    <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary">
                      <User className="h-4 w-4 text-primary-foreground" />
                    </div>
                  )}
                </div>
              );
            })}

            {/* Typing indicator */}
            {isLoading && (
              <div className="flex gap-3">
                <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary/10">
                  <Bot className="h-4 w-4 animate-pulse text-primary" />
                </div>
                <div className="flex items-center gap-1.5 rounded-xl bg-muted px-4 py-3">
                  <div className="h-1.5 w-1.5 animate-bounce rounded-full bg-primary/50" />
                  <div className="h-1.5 w-1.5 animate-bounce rounded-full bg-primary/50 [animation-delay:-.3s]" />
                  <div className="h-1.5 w-1.5 animate-bounce rounded-full bg-primary/50 [animation-delay:-.5s]" />
                </div>
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>

          {/* Input bar */}
          <div className="shrink-0 border-t bg-background px-4 py-3">
            <form
              className="flex gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                void sendMessage();
              }}
            >
              <input
                type="text"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder="e.g. What are the termination rights?"
                className="flex-1 rounded-lg border border-input bg-background px-4 py-2 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                disabled={isLoading}
              />
              <Button
                type="submit"
                size="sm"
                disabled={isLoading || !input.trim()}
              >
                <Send className="h-4 w-4" />
              </Button>
            </form>
          </div>
        </div>

        {/* ── Drag handle ── */}
        <div
          ref={dividerRef}
          className="pane-divider"
          onMouseDown={onMouseDownDivider}
        />

        {/* RIGHT: Document Viewer */}
        <div className="flex flex-1 flex-col overflow-hidden border-l">
          <DocumentViewer
            analysisId={selectedAnalysisId === "all" ? null : selectedAnalysisId}
            highlightedClauseId={highlightedClauseId}
          />
        </div>
      </div>
    </div>
  );
}