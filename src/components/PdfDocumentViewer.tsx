import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Document, Page, pdfjs } from "react-pdf";
import type { PDFDocumentProxy } from "pdfjs-dist";
import "react-pdf/dist/Page/AnnotationLayer.css";
import "react-pdf/dist/Page/TextLayer.css";
import { escapeHtml, planHighlight, type HighlightPlan } from "@/lib/pdfHighlight";
import { scrollWithin } from "@/lib/scrollWithin";

pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  "pdfjs-dist/build/pdf.worker.min.mjs",
  import.meta.url
).toString();

interface PdfDocumentViewerProps {
  fileUrl: string;
  highlightText: string | null;
  highlightKey: string | number | null;
  targetPage: number | null;
}

type TextRenderer = (item: { str: string; itemIndex: number }) => string;

const EMPTY_PLAN: HighlightPlan = { pages: new Map(), firstPage: null };

export default function PdfDocumentViewer({
  fileUrl,
  highlightText,
  highlightKey,
  targetPage,
}: PdfDocumentViewerProps) {
  const [pdf, setPdf] = useState<PDFDocumentProxy | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [plan, setPlan] = useState<HighlightPlan>(EMPTY_PLAN);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const pageRefs = useRef<Record<number, HTMLDivElement | null>>({});
  // The highlight we still need to scroll to once its page has rendered.
  const pendingScroll = useRef<string | number | null>(null);

  const numPages = pdf?.numPages ?? 0;

  // Work out exactly which text items belong to the selected clause, using
  // the same text items pdf.js renders (so indexes line up).
  useEffect(() => {
    if (!pdf || highlightKey == null || !highlightText) {
      setPlan(EMPTY_PLAN);
      return;
    }
    let cancelled = false;
    planHighlight(highlightText, pdf.numPages, targetPage, async (n) => {
      const page = await pdf.getPage(n);
      const content = await page.getTextContent();
      return content.items.map((item) => ("str" in item ? item.str : ""));
    })
      .then((next) => {
        if (cancelled) return;
        setPlan(next);
        pendingScroll.current = highlightKey;
        // Text not found (e.g. a scanned PDF without a text layer): at
        // least bring the reported page into view.
        const pageEl = targetPage ? pageRefs.current[targetPage] : null;
        if (next.firstPage == null && pageEl && containerRef.current) {
          scrollWithin(containerRef.current, pageEl, "start");
          pendingScroll.current = null;
        }
      })
      .catch(() => {
        if (!cancelled) setPlan(EMPTY_PLAN);
      });
    return () => {
      cancelled = true;
    };
  }, [pdf, highlightKey, highlightText, targetPage]);

  // One stable renderer per highlighted page, so pages only re-render their
  // text layer when their own highlight changes.
  const renderers = useMemo(() => {
    const map = new Map<number, TextRenderer>();
    plan.pages.forEach((items, pageNum) => {
      map.set(pageNum, ({ str, itemIndex }) =>
        items.has(itemIndex)
          ? `<mark class="pdf-clause-highlight">${escapeHtml(str)}</mark>`
          : escapeHtml(str)
      );
    });
    return map;
  }, [plan]);

  // Scroll to the first highlighted line once its page's text layer is
  // drawn. Handlers are stable per page (react-pdf redraws a text layer
  // whenever this callback changes identity).
  const firstPageRef = useRef<number | null>(null);
  firstPageRef.current = plan.firstPage;
  const scrollToHighlight = useCallback((pageNum: number) => {
    if (pendingScroll.current == null || pageNum !== firstPageRef.current) return;
    const pageEl = pageRefs.current[pageNum];
    const container = containerRef.current;
    if (!pageEl || !container) return;
    // Scroll only the viewer itself (see scrollWithin for why not
    // scrollIntoView).
    const mark = pageEl.querySelector(".pdf-clause-highlight");
    scrollWithin(container, mark ?? pageEl, mark ? "center" : "start");
    pendingScroll.current = null;
  }, []);
  const onTextRendered = useMemo(
    () => Array.from({ length: numPages + 1 }, (_, n) => () => scrollToHighlight(n)),
    [numPages, scrollToHighlight]
  );

  const width = Math.min(720, (containerRef.current?.clientWidth ?? 720) - 32);

  return (
    <div ref={containerRef} className="flex h-full flex-col overflow-y-auto bg-muted/30">
      <Document
        file={fileUrl}
        onLoadSuccess={(doc) => setPdf(doc as unknown as PDFDocumentProxy)}
        onLoadError={(err) => setLoadError(err.message)}
        loading={
          <div className="flex h-full items-center justify-center p-10 text-muted-foreground">
            <div className="flex flex-col items-center gap-3">
              <div className="h-6 w-6 animate-spin rounded-full border-2 border-primary border-t-transparent" />
              <p className="text-xs">Loading PDF…</p>
            </div>
          </div>
        }
        error={
          <div className="flex h-full items-center justify-center p-10 text-destructive text-sm">
            {loadError || "Failed to load the original PDF."}
          </div>
        }
      >
        <div className="flex flex-col items-center gap-4 py-4">
          {Array.from({ length: numPages }, (_, i) => i + 1).map((pageNum) => (
            <div
              key={pageNum}
              ref={(el) => {
                pageRefs.current[pageNum] = el;
              }}
              data-page-num={pageNum}
            >
              <Page
                pageNumber={pageNum}
                width={width}
                className="shadow-md"
                renderAnnotationLayer
                renderTextLayer
                customTextRenderer={renderers.get(pageNum)}
                onRenderTextLayerSuccess={onTextRendered[pageNum]}
              />
            </div>
          ))}
        </div>
      </Document>
    </div>
  );
}
