import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { History, Loader2, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  deleteConversation,
  getConversationId,
  listConversations,
  openConversation,
  type ConversationInfo,
} from "@/lib/chatSession";

/** "5 min ago", "yesterday", "3 Oct" - for the history list. */
export function timeAgo(iso?: string, now: Date = new Date()): string {
  if (!iso) return "";
  const then = new Date(iso);
  if (Number.isNaN(then.getTime())) return "";
  const minutes = Math.floor((now.getTime() - then.getTime()) / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.floor(hours / 24);
  if (days === 1) return "yesterday";
  if (days < 7) return `${days} days ago`;
  return then.toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

interface Props {
  /** An answer is being written; opening another conversation must wait. */
  disabled?: boolean;
  /** Called after a conversation is opened, with the contract it covered
   *  (null = all contracts). */
  onOpened: (analysisId: string | null) => void;
}

/**
 * The saved conversations, newest first. Conversations are saved on the
 * server after every answer, so they are still here after the browser is
 * closed. There are no user accounts: everyone using this app sees the
 * same list.
 */
export default function ChatHistory({ disabled, onOpened }: Props) {
  const [open, setOpen] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const { data, isLoading, isError } = useQuery<ConversationInfo[]>({
    queryKey: ["conversations"],
    queryFn: listConversations,
    enabled: open,
    staleTime: 0,
  });
  const conversations = data || [];
  const currentId = open ? getConversationId() : null;

  const handleOpen = async (id: string) => {
    setBusyId(id);
    setError(null);
    try {
      onOpened(await openConversation(id));
      setOpen(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not open this conversation.");
    } finally {
      setBusyId(null);
    }
  };

  const handleDelete = async (id: string) => {
    setBusyId(id);
    setError(null);
    try {
      await deleteConversation(id);
      await queryClient.invalidateQueries({ queryKey: ["conversations"] });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not delete this conversation.");
    } finally {
      setBusyId(null);
    }
  };

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button variant="ghost" size="sm" className="h-8 text-xs" title="Earlier conversations">
          <History className="mr-1 h-3.5 w-3.5" /> History
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-96 p-0">
        <div className="border-b px-3 py-2 text-xs font-semibold">Earlier conversations</div>
        <div className="max-h-96 overflow-y-auto">
          {isLoading && (
            <div className="flex items-center gap-2 px-3 py-4 text-xs text-muted-foreground">
              <Loader2 className="h-3.5 w-3.5 animate-spin" /> Loading…
            </div>
          )}
          {isError && (
            <p className="px-3 py-4 text-xs text-destructive">
              Could not load the history. Is the backend running?
            </p>
          )}
          {!isLoading && !isError && conversations.length === 0 && (
            <p className="px-3 py-4 text-xs text-muted-foreground">
              No saved conversations yet. A conversation is saved once it has its first answer.
            </p>
          )}
          {conversations.map((c) => (
            <div
              key={c.id}
              className={`group flex items-start gap-1 border-b border-border/40 px-1 last:border-b-0 ${
                c.id === currentId ? "bg-primary/5" : ""
              }`}
            >
              <button
                type="button"
                disabled={disabled || busyId !== null}
                onClick={() => handleOpen(c.id)}
                className="min-w-0 flex-1 rounded px-2 py-2 text-left hover:bg-muted disabled:opacity-50"
                title={disabled ? "Wait for the current answer to finish" : "Open this conversation"}
              >
                <p className="truncate text-sm">{c.title}</p>
                <p className="mt-0.5 text-[11px] text-muted-foreground">
                  {timeAgo(c.updated_at)}
                  {" · "}
                  {c.messages} message{c.messages === 1 ? "" : "s"}
                  {c.id === currentId ? " · open now" : ""}
                </p>
              </button>
              <button
                type="button"
                aria-label={`Delete conversation: ${c.title}`}
                title="Delete this conversation"
                disabled={busyId !== null || (disabled && c.id === currentId)}
                onClick={() => handleDelete(c.id)}
                className="mt-2 rounded p-1.5 text-muted-foreground opacity-60 hover:bg-destructive/10 hover:text-destructive group-hover:opacity-100 disabled:opacity-30"
              >
                {busyId === c.id ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}
              </button>
            </div>
          ))}
        </div>
        {error && <p className="border-t px-3 py-2 text-xs text-destructive">{error}</p>}
      </PopoverContent>
    </Popover>
  );
}
