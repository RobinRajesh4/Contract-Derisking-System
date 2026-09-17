import { useEffect, useRef, useState } from "react";
import { Document, Page, pdfjs } from "react-pdf";
import "react-pdf/dist/Page/AnnotationLayer.css";
import "react-pdf/dist/Page/TextLayer.css";

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

function normalize(s: string): string {
  return s.replace(/\s+/g, " ").trim().toLowerCase();
}

export default function PdfDocumentViewer({
  fileUrl,
  highlightText,
  highlightKey,
  targetPage,
}: PdfDocumentViewerProps) {
  const [numPages, setNumPages] = useState<number>(0);
  const [loadError, setLoadError] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const pageRefs = useRef<Record<number, HTMLDivElement | null>>({});

  const normalizedClauseText = highlightText ? normalize(highlightText) : "";

  useEffect(() => {
    if (!highlightKey || !targetPage || numPages === 0) return;

    const timer = setTimeout(() => {
      const pageEl = pageRefs.current[targetPage];
      pageEl?.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 150);

    return () => clearTimeout(timer);
  }, [highlightKey, targetPage, numPages]);

  return (
    <div ref={containerRef} className="flex h-full flex-col overflow-y-auto bg-muted/30">
      <Document
        file={fileUrl}
        onLoadSuccess={({ numPages }) => setNumPages(numPages)}
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
          {Array.from({ length: numPages }, (_, i) => i + 1).map((pageNum) => {
            const isTargetPage = pageNum === targetPage;

            return (
              <div
                key={pageNum}
                ref={(el) => {
                  pageRefs.current[pageNum] = el;
                }}
                data-page-num={pageNum}
              >
                <Page
                  key={`page-${pageNum}-${isTargetPage ? highlightKey ?? "none" : "static"}`}
                  pageNumber={pageNum}
                  width={Math.min(720, (containerRef.current?.clientWidth ?? 720) - 32)}
                  className="shadow-md"
                  renderAnnotationLayer
                  renderTextLayer
                  customTextRenderer={
                    isTargetPage && normalizedClauseText
                      ? ({ str }) => {
                          const itemNorm = normalize(str);
                          if (
                            itemNorm.length >= 8 &&
                            normalizedClauseText.includes(itemNorm)
                          ) {
                            return `<mark class="pdf-clause-highlight">${str}</mark>`;
                          }
                          return str;
                        }
                      : undefined
                  }
                />
              </div>
            );
          })}
        </div>
      </Document>
    </div>
  );
}