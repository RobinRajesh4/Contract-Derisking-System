import {
  useEffect,
  useRef,
  useState,
} from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  Bot,
  FileText,
  Send,
  User,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { listAnalyses } from "@/services/analysis";

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

export default function Chat() {
  const [messages, setMessages] = useState<Message[]>(() => {
    const savedMessages = sessionStorage.getItem(
      "contract-chat-messages"
    );

    if (savedMessages) {
      try {
        return JSON.parse(savedMessages) as Message[];
      } catch {
        sessionStorage.removeItem(
          "contract-chat-messages"
        );
      }
    }

    return [
      {
        role: "assistant",
        content:
          "Hello! I can answer questions about contracts " +
          "that have been uploaded and indexed. What would " +
          "you like to know?",
      },
    ];
  });

  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);

  const [
    selectedAnalysisId,
    setSelectedAnalysisId,
  ] = useState(
    () =>
      sessionStorage.getItem(
        "contract-chat-selected-analysis"
      ) || "all"
  );

  useEffect(() => {
    sessionStorage.setItem(
      "contract-chat-selected-analysis",
      selectedAnalysisId
    );
  }, [selectedAnalysisId]);

  const {
    data: analysesData,
    isLoading: isLoadingAnalyses,
    isError: isAnalysesError,
  } = useQuery({
    queryKey: ["analyses"],
    queryFn: () => listAnalyses(),
  });

  const analyses =
    (analysesData as any[] | undefined) || [];

  const selectedAnalysis =
    selectedAnalysisId === "all"
      ? null
      : analyses.find(
          (analysis: any) =>
            analysis.analysis_id ===
            selectedAnalysisId
        );

  const messagesEndRef =
    useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({
      behavior: "smooth",
    });
  }, [messages]);

  useEffect(() => {
    sessionStorage.setItem(
      "contract-chat-messages",
      JSON.stringify(messages)
    );
  }, [messages]);

  const sendMessage = async () => {
    const question = input.trim();

    if (!question || isLoading) {
      return;
    }

    setInput("");

    setMessages((previous) => [
      ...previous,
      {
        role: "user",
        content: question,
      },
    ]);

    setIsLoading(true);

    try {
      const requestBody: {
        message: string;
        top_k: number;
        analysis_id?: string;
      } = {
        message: question,
        top_k: 5,
      };

      if (selectedAnalysisId !== "all") {
        requestBody.analysis_id =
          selectedAnalysisId;
      }

      const response = await fetch(
        "http://127.0.0.1:8001/chat",
        {
          method: "POST",
          headers: {
            "Content-Type":
              "application/json",
          },
          body: JSON.stringify(requestBody),
        }
      );

      const data = await response.json();

      if (!response.ok) {
        throw new Error(
          data.detail ||
            "Failed to get a response"
        );
      }

      setMessages((previous) => [
        ...previous,
        {
          role: "assistant",
          content:
            data.reply ||
            "The AI returned an empty response.",
          sources: data.sources || [],
        },
      ]);
    } catch (error) {
      const message =
        error instanceof Error
          ? error.message
          : "Unknown connection error";

      setMessages((previous) => [
        ...previous,
        {
          role: "assistant",
          content:
            "Sorry, the contract assistant could not " +
            `complete the request. ${message}`,
        },
      ]);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="flex h-[calc(100vh-8rem)] flex-col overflow-hidden rounded-lg border bg-background shadow-sm">
      <div className="border-b bg-muted px-6 py-4">
        <h2 className="flex items-center gap-2 text-lg font-semibold">
          <Bot className="h-5 w-5" />
          Ask AI
        </h2>

        <p className="text-sm text-muted-foreground">
          Search across uploaded and indexed contracts
        </p>

        <div className="mt-3 max-w-sm">
          <Select
            value={selectedAnalysisId}
            onValueChange={
              setSelectedAnalysisId
            }
            disabled={isLoadingAnalyses}
          >
            <SelectTrigger>
              <SelectValue placeholder="Select contract" />
            </SelectTrigger>

            <SelectContent>
              <SelectItem value="all">
                All Contracts
              </SelectItem>

              {analyses.map(
                (analysis: any) => (
                  <SelectItem
                    key={
                      analysis.analysis_id
                    }
                    value={
                      analysis.analysis_id
                    }
                  >
                    {analysis.filename ||
                      `Analysis ${analysis.analysis_id?.slice(
                        0,
                        8
                      )}`}
                  </SelectItem>
                )
              )}
            </SelectContent>
          </Select>

          {isLoadingAnalyses && (
            <p className="mt-2 text-xs text-muted-foreground">
              Loading contracts...
            </p>
          )}

          {isAnalysesError && (
            <p className="mt-2 text-xs text-destructive">
              Failed to load contracts.
            </p>
          )}

          {!isLoadingAnalyses &&
            !isAnalysesError &&
            analyses.length === 0 && (
              <p className="mt-2 text-xs text-muted-foreground">
                No uploaded contracts are
                available.
              </p>
            )}

          {!isLoadingAnalyses &&
            analyses.length > 0 && (
              <p className="mt-2 text-xs text-muted-foreground">
                {selectedAnalysisId ===
                "all"
                  ? `Searching across all ${analyses.length} contracts`
                  : `Searching only: ${
                      selectedAnalysis?.filename ||
                      `Analysis ${selectedAnalysisId.slice(
                        0,
                        8
                      )}`
                    }`}
              </p>
            )}
        </div>
      </div>

      <div className="flex-1 space-y-6 overflow-y-auto p-6">
        {messages.map(
          (message, index) => (
            <div
              key={index}
              className={`flex gap-4 ${
                message.role === "user"
                  ? "justify-end"
                  : ""
              }`}
            >
              {message.role ===
                "assistant" && (
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary/10">
                  <Bot className="h-5 w-5 text-primary" />
                </div>
              )}

              <div
                className={`max-w-[80%] rounded-lg p-4 ${
                  message.role === "user"
                    ? "bg-primary text-primary-foreground"
                    : "bg-muted"
                }`}
              >
                <p className="whitespace-pre-wrap">
                  {message.content}
                </p>

                {message.sources &&
                  message.sources.length >
                    0 && (
                    <div className="mt-4 border-t border-border/50 pt-4">
                      <p className="mb-2 text-xs font-semibold opacity-80">
                        Sources used
                      </p>

                      <div className="space-y-2">
                        {message.sources.map(
                          (
                            source,
                            sourceIndex
                          ) =>
                            source.analysis_id ? (
                              <Link
                                key={
                                  sourceIndex
                                }
                                to={`/analyses/${source.analysis_id}`}
                                className="flex items-start gap-2 rounded border border-border/50 bg-background/50 p-2 text-xs transition-colors hover:border-primary/50 hover:bg-background"
                              >
                                <FileText className="mt-0.5 h-3 w-3 shrink-0" />

                                <div className="min-w-0">
                                  <p className="line-clamp-3 opacity-80">
                                    {
                                      source.text
                                    }
                                  </p>

                                  <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-muted-foreground">
                                    {source.clause_id !==
                                      undefined && (
                                      <span>
                                        Clause:{" "}
                                        {
                                          source.clause_id
                                        }
                                      </span>
                                    )}

                                    {typeof source.score ===
                                      "number" && (
                                      <span>
                                        Relevance:{" "}
                                        {source.score.toFixed(
                                          3
                                        )}
                                      </span>
                                    )}

                                    <span className="font-medium text-primary">
                                      Open contract
                                    </span>
                                  </div>
                                </div>
                              </Link>
                            ) : (
                              <div
                                key={
                                  sourceIndex
                                }
                                className="flex items-start gap-2 rounded border border-border/50 bg-background/50 p-2 text-xs"
                              >
                                <FileText className="mt-0.5 h-3 w-3 shrink-0" />

                                <div className="min-w-0">
                                  <p className="line-clamp-3 opacity-80">
                                    {
                                      source.text
                                    }
                                  </p>

                                  <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-muted-foreground">
                                    {source.clause_id !==
                                      undefined && (
                                      <span>
                                        Clause:{" "}
                                        {
                                          source.clause_id
                                        }
                                      </span>
                                    )}

                                    {typeof source.score ===
                                      "number" && (
                                      <span>
                                        Relevance:{" "}
                                        {source.score.toFixed(
                                          3
                                        )}
                                      </span>
                                    )}
                                  </div>
                                </div>
                              </div>
                            )
                        )}
                      </div>
                    </div>
                  )}
              </div>

              {message.role === "user" && (
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary">
                  <User className="h-5 w-5 text-primary-foreground" />
                </div>
              )}
            </div>
          )
        )}

        {isLoading && (
          <div className="flex gap-4">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary/10">
              <Bot className="h-5 w-5 animate-pulse text-primary" />
            </div>

            <div className="flex items-center gap-1 rounded-lg bg-muted p-4">
              <div className="h-2 w-2 animate-bounce rounded-full bg-primary/50" />

              <div className="h-2 w-2 animate-bounce rounded-full bg-primary/50 [animation-delay:-.3s]" />

              <div className="h-2 w-2 animate-bounce rounded-full bg-primary/50 [animation-delay:-.5s]" />
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      <div className="border-t bg-background p-4">
        <form
          className="flex gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            void sendMessage();
          }}
        >
          <input
            type="text"
            value={input}
            onChange={(event) =>
              setInput(event.target.value)
            }
            placeholder="Example: What are the termination rights?"
            className="flex-1 rounded-md border border-input bg-background px-4 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            disabled={isLoading}
          />

          <Button
            type="submit"
            disabled={
              isLoading || !input.trim()
            }
          >
            <Send className="h-4 w-4" />
          </Button>
        </form>
      </div>
    </div>
  );
}