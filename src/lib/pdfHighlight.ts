/**
 * Finds exactly which text items of a PDF page belong to a clause, so the
 * viewer highlights that clause and nothing else.
 *
 * The clause text comes from the backend's parser (extracted with pypdf and
 * cleaned up), while the viewer shows pdf.js's text items. The two never
 * agree on whitespace, line breaks, hyphenation or ligatures, and the
 * parser drops boilerplate such as "Page 2 of 3". So both sides are reduced
 * to a "compact" form (letters and digits only) and aligned character by
 * character, re-synchronising across small gaps.
 *
 * The old approach marked every text item of 8+ characters that appeared
 * *anywhere* inside the clause text. That highlighted stray phrases in other
 * clauses ("the BORROWER shall"), skipped short items, and only looked at one
 * page, so clauses that continued on the next page were half highlighted.
 */

/** Letters and digits only, lower-cased, ligatures expanded. */
export function compact(s: string): string {
  return (s || "")
    .normalize("NFKC")
    .toLowerCase()
    .replace(/[^\p{L}\p{N}]/gu, "");
}

interface CompactPage {
  text: string;
  /** owner[i] = index of the text item that produced text[i] */
  owner: number[];
}

function compactPage(items: string[]): CompactPage {
  let text = "";
  const owner: number[] = [];
  items.forEach((str, idx) => {
    const c = compact(str);
    text += c;
    for (let k = 0; k < c.length; k++) owner.push(idx);
  });
  return { text, owner };
}

const ANCHOR_LEN = 40;
const MIN_ANCHOR = 12;
const PROBE = 12;
const MAX_GAP = 400;

/** How far into a page a continued clause may resume (room for a running header). */
const CONTINUATION_WINDOW = 300;

function findAnchor(page: string, clause: string, continuation: boolean): number {
  // A clause that continues from the previous page resumes near the top
  // of this one. Looking only there also lets a short tail ("clause.")
  // be matched without latching onto the same word further down.
  if (continuation) {
    const anchor = clause.slice(0, ANCHOR_LEN);
    const pos = page.indexOf(anchor);
    return pos >= 0 && pos <= CONTINUATION_WINDOW ? pos : -1;
  }
  // Try a long, distinctive opening first, then shorter ones.
  for (const len of [ANCHOR_LEN, 24, MIN_ANCHOR]) {
    const anchor = clause.slice(0, Math.min(len, clause.length));
    if (anchor.length < Math.min(MIN_ANCHOR, clause.length)) break;
    const pos = page.indexOf(anchor);
    if (pos >= 0) return pos;
  }
  return -1;
}

export interface PageMatch {
  /** text item indexes to highlight */
  items: Set<number>;
  /** compact clause characters matched on this page */
  consumed: number;
}

/**
 * Align `clause` (compact) against one page, starting where the clause's
 * opening appears. Returns null if the opening isn't on this page.
 */
export function matchOnPage(
  items: string[],
  clause: string,
  continuation = false
): PageMatch | null {
  if (!clause) return null;
  const page = compactPage(items);
  const start = findAnchor(page.text, clause, continuation);
  if (start < 0) return null;

  const marked = new Set<number>();
  let ci = 0;
  let pi = start;
  while (ci < clause.length && pi < page.text.length) {
    if (page.text[pi] === clause[ci]) {
      marked.add(page.owner[pi]);
      ci++;
      pi++;
      continue;
    }
    // Page has extra text the clause doesn't (e.g. "Page 2 of 3" the
    // parser removed): skip ahead in the page to where the clause resumes.
    const probe = clause.slice(ci, ci + PROBE);
    const j = probe.length >= 6 ? page.text.indexOf(probe, pi) : -1;
    if (j >= 0 && j - pi <= MAX_GAP) {
      pi = j;
      continue;
    }
    // Clause has text the page doesn't (the reverse): skip ahead in the clause.
    const back = page.text.slice(pi, pi + PROBE);
    const k = back.length >= 6 ? clause.indexOf(back, ci) : -1;
    if (k >= 0 && k - ci <= MAX_GAP) {
      ci = k;
      continue;
    }
    break;
  }
  return { items: marked, consumed: ci };
}

export interface HighlightPlan {
  /** page number -> text item indexes to highlight on that page */
  pages: Map<number, Set<number>>;
  /** the page where the clause starts (scroll target) */
  firstPage: number | null;
}

/**
 * Decide what to highlight for one clause across the whole document.
 * Starts on the page the backend reported, but searches the other pages
 * (nearest first) if the clause isn't there, then follows the clause onto
 * the next pages while it continues.
 */
export async function planHighlight(
  clauseText: string,
  numPages: number,
  targetPage: number | null,
  getPageItems: (pageNumber: number) => Promise<string[]>
): Promise<HighlightPlan> {
  const clause = compact(clauseText);
  const plan: HighlightPlan = { pages: new Map(), firstPage: null };
  if (!clause || numPages < 1) return plan;

  const cache = new Map<number, string[]>();
  const itemsOf = async (p: number) => {
    if (!cache.has(p)) cache.set(p, await getPageItems(p));
    return cache.get(p)!;
  };

  const first = targetPage && targetPage >= 1 && targetPage <= numPages ? targetPage : 1;
  const order: number[] = [first];
  for (let d = 1; d < numPages; d++) {
    if (first + d <= numPages) order.push(first + d);
    if (first - d >= 1) order.push(first - d);
  }

  for (const p of order) {
    const m = matchOnPage(await itemsOf(p), clause);
    if (!m || m.items.size === 0) continue;

    plan.firstPage = p;
    plan.pages.set(p, m.items);
    let remaining = clause.slice(m.consumed);
    let page = p + 1;
    // Follow the clause onto the following pages.
    while (remaining.length >= 4 && page <= numPages) {
      const next = matchOnPage(await itemsOf(page), remaining, true);
      if (!next || next.items.size === 0) break;
      plan.pages.set(page, next.items);
      remaining = remaining.slice(next.consumed);
      page++;
    }
    return plan;
  }
  return plan;
}

export function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
