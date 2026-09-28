import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import {
  Upload as UploadIcon,
  FolderOpen,
  FileText,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  Loader2,
  MinusCircle,
  Clock,
} from "lucide-react";
import { useToast } from "@/hooks/use-toast";
import {
  clearFinished,
  enqueue,
  retryFailed,
  stop,
  subscribe,
  type QueueItem,
} from "@/lib/uploadQueue";

/** Every file inside dropped folders (drag-and-drop gives entries, not files). */
async function filesFromDrop(dataTransfer: DataTransfer): Promise<File[]> {
  const entries = Array.from(dataTransfer.items || [])
    .map((item) => (item.webkitGetAsEntry ? item.webkitGetAsEntry() : null))
    .filter(Boolean) as FileSystemEntry[];
  if (!entries.length) return Array.from(dataTransfer.files || []);

  const out: File[] = [];
  const walk = async (entry: FileSystemEntry, prefix: string): Promise<void> => {
    if (entry.isFile) {
      const file = await new Promise<File>((resolve, reject) =>
        (entry as FileSystemFileEntry).file(resolve, reject)
      );
      Object.defineProperty(file, "webkitRelativePath", { value: prefix + file.name });
      out.push(file);
    } else if (entry.isDirectory) {
      const reader = (entry as FileSystemDirectoryEntry).createReader();
      // readEntries returns results in chunks; call until empty.
      for (;;) {
        const batch = await new Promise<FileSystemEntry[]>((resolve, reject) =>
          reader.readEntries(resolve, reject)
        );
        if (!batch.length) break;
        for (const child of batch) await walk(child, prefix + entry.name + "/");
      }
    }
  };
  for (const entry of entries) await walk(entry, "");
  return out;
}

const STATUS_LABEL: Record<QueueItem["status"], string> = {
  queued: "Waiting",
  uploading: "Uploading…",
  analyzing: "Analyzing…",
  done: "Done",
  warning: "Done, with warnings",
  failed: "Failed",
  skipped: "Skipped",
};

function StatusIcon({ status }: { status: QueueItem["status"] }) {
  switch (status) {
    case "done":
      return <CheckCircle2 className="h-4 w-4 text-green-600" />;
    case "warning":
      return <AlertTriangle className="h-4 w-4 text-amber-600" />;
    case "failed":
      return <XCircle className="h-4 w-4 text-destructive" />;
    case "skipped":
      return <MinusCircle className="h-4 w-4 text-muted-foreground" />;
    case "queued":
      return <Clock className="h-4 w-4 text-muted-foreground" />;
    default:
      return <Loader2 className="h-4 w-4 animate-spin text-primary" />;
  }
}

export default function Upload() {
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const [items, setItems] = useState<QueueItem[]>([]);
  const [running, setRunning] = useState(false);
  const [dragging, setDragging] = useState(false);
  const folderInput = useRef<HTMLInputElement>(null);
  const finishedCount = useRef(0);

  useEffect(
    () =>
      subscribe((next, isRunning) => {
        setItems(next);
        setRunning(isRunning);
        // Refresh contract lists as files finish, so other pages are current.
        const finished = next.filter((i) => ["done", "warning", "failed"].includes(i.status)).length;
        if (finished !== finishedCount.current) {
          finishedCount.current = finished;
          void queryClient.invalidateQueries({ queryKey: ["analyses"] });
        }
      }),
    [queryClient]
  );

  // Folder picking isn't a standard attribute in React's types.
  useEffect(() => {
    folderInput.current?.setAttribute("webkitdirectory", "");
    folderInput.current?.setAttribute("directory", "");
  }, []);

  const add = (files: File[]) => {
    if (!files.length) return;
    const { added, skipped } = enqueue(files);
    toast({
      title: added ? `${added} contract${added === 1 ? "" : "s"} queued` : "No PDF files found",
      description: skipped ? `${skipped} file${skipped === 1 ? "" : "s"} skipped (not PDF or too large).` : undefined,
      variant: added ? "default" : "destructive",
    });
  };

  const onPick = (e: React.ChangeEvent<HTMLInputElement>) => {
    add(Array.from(e.target.files || []));
    e.target.value = ""; // allow picking the same folder again
  };

  const counts = items.reduce(
    (acc, i) => {
      acc[i.status] = (acc[i.status] || 0) + 1;
      return acc;
    },
    {} as Record<string, number>
  );
  const pdfItems = items.filter((i) => i.message !== "Not a PDF");
  const handled = pdfItems.filter((i) => ["done", "warning", "failed", "skipped"].includes(i.status)).length;
  const current = items.find((i) => i.status === "uploading" || i.status === "analyzing");
  const failedWithFile = items.some((i) => i.status === "failed");

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Upload Contracts</h1>
        <p className="text-muted-foreground">
          Upload one contract or a whole folder; each PDF is analyzed against your policy library
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Contract documents</CardTitle>
          <CardDescription>
            Pick PDF files or a folder (sub-folders included). Files are analyzed one after another; you can keep
            using the app meanwhile. Files already uploaded and analyzed are not analyzed again.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div
            onDragOver={(e) => {
              e.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={async (e) => {
              e.preventDefault();
              setDragging(false);
              add(await filesFromDrop(e.dataTransfer));
            }}
            className={`flex flex-col items-center justify-center w-full h-56 border-2 border-dashed rounded-lg transition-colors ${
              dragging ? "bg-primary/10 border-primary" : "bg-muted/30"
            }`}
          >
            <UploadIcon className="w-10 h-10 mb-3 text-muted-foreground" />
            <p className="mb-4 text-sm text-muted-foreground">Drag PDF files or folders here, or</p>
            <div className="flex flex-wrap justify-center gap-3">
              <Button asChild variant="outline">
                <label className="cursor-pointer">
                  <FileText className="mr-2 h-4 w-4" />
                  Choose files
                  <input type="file" className="hidden" accept=".pdf" multiple onChange={onPick} />
                </label>
              </Button>
              <Button asChild>
                <label className="cursor-pointer">
                  <FolderOpen className="mr-2 h-4 w-4" />
                  Choose folder
                  <input ref={folderInput} type="file" className="hidden" multiple onChange={onPick} />
                </label>
              </Button>
            </div>
            <p className="mt-3 text-xs text-muted-foreground">PDF files only (max 50 MB each)</p>
          </div>

          {items.length > 0 && (
            <div className="space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="text-sm">
                  <span className="font-medium">
                    {handled} of {pdfItems.length} processed
                  </span>
                  <span className="ml-3 text-muted-foreground">
                    {counts.done ? `${counts.done} done` : ""}
                    {counts.warning ? ` · ${counts.warning} with warnings` : ""}
                    {counts.failed ? ` · ${counts.failed} failed` : ""}
                    {counts.skipped ? ` · ${counts.skipped} skipped` : ""}
                  </span>
                </div>
                <div className="flex gap-2">
                  {running && (
                    <Button size="sm" variant="outline" onClick={stop}>
                      Stop after current file
                    </Button>
                  )}
                  {!running && failedWithFile && (
                    <Button size="sm" variant="outline" onClick={() => retryFailed()}>
                      Retry failed
                    </Button>
                  )}
                  {!running && (
                    <Button size="sm" variant="ghost" onClick={clearFinished}>
                      Clear list
                    </Button>
                  )}
                </div>
              </div>
              <Progress value={pdfItems.length ? (handled / pdfItems.length) * 100 : 0} />
              {current && (
                <p className="text-xs text-muted-foreground">
                  {STATUS_LABEL[current.status]} {current.path}
                </p>
              )}

              <div className="max-h-[420px] overflow-y-auto rounded-md border divide-y">
                {items.map((item) => (
                  <div key={item.id} className="flex items-start gap-3 px-3 py-2 text-sm">
                    <div className="mt-0.5">
                      <StatusIcon status={item.status} />
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-baseline gap-x-2">
                        <span className="truncate font-medium" title={item.path}>
                          {item.path}
                        </span>
                        <span className="text-xs text-muted-foreground">{STATUS_LABEL[item.status]}</span>
                      </div>
                      {item.message && (
                        <p
                          className={`text-xs ${
                            item.status === "failed"
                              ? "text-destructive"
                              : item.status === "warning"
                                ? "text-amber-700"
                                : "text-muted-foreground"
                          }`}
                        >
                          {item.message}
                        </p>
                      )}
                    </div>
                    {item.analysisId && ["done", "warning", "failed"].includes(item.status) && (
                      <Link to={`/analyses/${item.analysisId}`} className="shrink-0 text-xs text-primary underline">
                        Open
                      </Link>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>How it works</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm text-muted-foreground">
          <p>1. Pick contract PDFs or a whole folder</p>
          <p>2. Each file's text is extracted (with OCR for scanned pages) and split into clauses</p>
          <p>3. Each clause is compared against your policy library</p>
          <p>4. Risk scores are calculated based on policy violations</p>
          <p>5. Review detailed results with recommendations, or ask the chatbot across all contracts</p>
        </CardContent>
      </Card>
    </div>
  );
}
