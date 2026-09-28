/**
 * Uploads and analyzes many contracts (a whole folder) one after another.
 *
 * Lives outside the Upload page so the batch keeps going when the user
 * opens other pages (the page only shows the progress). Files go one at a
 * time: the shared AI server is the bottleneck, and each analysis already
 * runs its clauses in parallel.
 *
 * Re-running the same folder is cheap: a file that's already stored and
 * analyzed with unchanged text is not analyzed again.
 */
import { getAnalysis, runAnalysis, uploadContract, uploadWarnings } from "@/services/analysis";
import { analysisState } from "@/lib/analysisStatus";

export type ItemStatus =
  | "queued"
  | "uploading"
  | "analyzing"
  | "done"
  | "warning"
  | "failed"
  | "skipped";

export interface QueueItem {
  id: number;
  name: string;
  path: string;
  size: number;
  status: ItemStatus;
  message?: string;
  analysisId?: string;
  file?: File;
}

const MAX_BYTES = 50 * 1024 * 1024;

let items: QueueItem[] = [];
let running = false;
let stopRequested = false;
let nextId = 1;
type Listener = (items: QueueItem[], running: boolean) => void;
const listeners = new Set<Listener>();

function publish() {
  const snapshot = items.map(({ file, ...rest }) => ({ ...rest }));
  listeners.forEach((l) => l(snapshot as QueueItem[], running));
}

function update(id: number, patch: Partial<QueueItem>) {
  items = items.map((it) => (it.id === id ? { ...it, ...patch } : it));
  publish();
}

export function subscribe(listener: Listener): () => void {
  listeners.add(listener);
  listener(items.map(({ file, ...rest }) => ({ ...rest })) as QueueItem[], running);
  return () => listeners.delete(listener);
}

export function isRunning(): boolean {
  return running;
}

function pathOf(file: File): string {
  return (file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name;
}

/** Add files (e.g. every file of a picked folder) and start processing. */
export function enqueue(files: File[]): { added: number; skipped: number } {
  let added = 0;
  let skipped = 0;
  const known = new Set(items.filter((i) => i.status === "queued").map((i) => i.path + ":" + i.size));
  for (const file of files) {
    const path = pathOf(file);
    const base = { id: nextId++, name: file.name, path, size: file.size };
    if (!file.name.toLowerCase().endsWith(".pdf")) {
      // Hidden/system files in a folder (Thumbs.db, desktop.ini) aren't worth listing.
      if (!file.name.startsWith(".") && !/^(thumbs\.db|desktop\.ini)$/i.test(file.name)) {
        items.push({ ...base, status: "skipped", message: "Not a PDF" });
        skipped++;
      }
      continue;
    }
    if (file.size > MAX_BYTES) {
      items.push({ ...base, status: "skipped", message: "Larger than 50 MB" });
      skipped++;
      continue;
    }
    if (known.has(path + ":" + file.size)) continue; // same file picked twice
    known.add(path + ":" + file.size);
    items.push({ ...base, status: "queued", file });
    added++;
  }
  publish();
  void run();
  return { added, skipped };
}

async function processOne(item: QueueItem) {
  const file = item.file!;
  update(item.id, { status: "uploading", message: undefined });
  let uploaded;
  try {
    uploaded = await uploadContract(file);
  } catch (error) {
    update(item.id, { status: "failed", message: error instanceof Error ? error.message : "Upload failed" });
    return;
  }
  const notes = uploadWarnings(uploaded);
  update(item.id, { analysisId: uploaded.analysis_id });

  // Same file as before, text unchanged, already analyzed: nothing to redo.
  if (uploaded.reprocessed && !uploaded.clauses_changed) {
    try {
      const existing = await getAnalysis(uploaded.analysis_id);
      if (analysisState(existing) === "analyzed") {
        update(item.id, {
          status: "done",
          message: uploaded.duplicate_of
            ? `Same file as "${uploaded.duplicate_of}" - already analyzed, not added again`
            : "Already uploaded and analyzed",
        });
        return;
      }
    } catch {
      /* fall through and analyze */
    }
  }

  update(item.id, { status: "analyzing" });
  try {
    const result = await runAnalysis(uploaded.analysis_id);
    const quality = result.analysis_quality;
    if (quality && quality.complete === false && quality.message) notes.push(quality.message);
    update(item.id, {
      status: notes.length ? "warning" : "done",
      message: notes.length ? notes.join(" ") : `Analyzed ${result.total_clauses} clauses`,
    });
  } catch (error) {
    update(item.id, {
      status: "failed",
      message:
        "Uploaded, but the analysis failed: " +
        (error instanceof Error ? error.message : "the AI server didn't respond") +
        ". Open the contract to run it again.",
    });
  }
}

async function run() {
  if (running) return;
  running = true;
  stopRequested = false;
  publish();
  try {
    for (;;) {
      if (stopRequested) break;
      const next = items.find((i) => i.status === "queued");
      if (!next) break;
      await processOne(next);
      // Drop the file data once handled (kept for a failure, so it can be
      // retried without picking the folder again).
      items = items.map((i) => (i.id === next.id && i.status !== "failed" ? { ...i, file: undefined } : i));
    }
  } finally {
    running = false;
    if (stopRequested) {
      items = items.map((i) =>
        i.status === "queued" ? { ...i, status: "skipped", message: "Stopped before processing", file: undefined } : i
      );
    }
    stopRequested = false;
    publish();
  }
}

/** Finish the file in progress, then stop. */
export function stop(): void {
  if (running) {
    stopRequested = true;
    publish();
  }
}

/** Remove finished rows (keeps queued and in-progress ones). */
export function clearFinished(): void {
  items = items.filter((i) => i.status === "queued" || i.status === "uploading" || i.status === "analyzing");
  publish();
}

/** Put failed rows back in the queue (only possible while their file is still held). */
export function retryFailed(): number {
  let n = 0;
  items = items.map((i) => {
    if (i.status === "failed" && i.file) {
      n++;
      return { ...i, status: "queued", message: undefined };
    }
    return i;
  });
  publish();
  if (n) void run();
  return n;
}
