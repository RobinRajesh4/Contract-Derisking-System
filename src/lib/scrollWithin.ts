/**
 * Scroll `container` so that `target` (somewhere inside it) is in view,
 * without touching any other element.
 *
 * Element.scrollIntoView() is not safe here: it scrolls *every* scrollable
 * ancestor of the target, including ones with `overflow: hidden`. In the
 * PDF viewer one of those ancestors is pdf.js's text layer, which clips its
 * overflow. When a page has text that pokes past the page edge (a
 * watermark, a stamp, a footer), the text layer can scroll a few pixels,
 * and scrollIntoView did exactly that for clauses further down the page.
 * The highlights then sat over the gaps between lines instead of the words,
 * until a resize redrew the layer.
 */
export function scrollWithin(
  container: HTMLElement,
  target: Element,
  block: "start" | "center" = "center",
  behavior: ScrollBehavior = "smooth"
): void {
  const box = container.getBoundingClientRect();
  const rect = target.getBoundingClientRect();
  const offset = rect.top - box.top - container.clientTop + container.scrollTop;
  const top =
    block === "center"
      ? offset - (container.clientHeight - rect.height) / 2
      : offset - 8;
  container.scrollTo({ top: Math.max(0, top), behavior });
}
