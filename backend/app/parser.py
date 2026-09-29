import re
from typing import List, Dict, Any, Optional, Tuple
from pypdf import PdfReader
from io import BytesIO
import os
import platform
import shutil
import glob

# Configure Tesseract and Poppler paths for Windows
if platform.system() == 'Windows':
    print("Configuring for Windows...")

    # ── Tesseract ─────────────────────────────────────────────
    # 1) Already on PATH (e.g. installer's "Add to PATH" was checked)
    # 2) TESSERACT_PATH env var, if set
    # 3) Common default install locations
    tesseract_path = (
        shutil.which("tesseract")
        or os.environ.get("TESSERACT_PATH")
        or next(
            (
                p for p in [
                    r'C:\Program Files\Tesseract-OCR\tesseract.exe',
                    r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe',
                    os.path.expandvars(r'%LOCALAPPDATA%\Tesseract-OCR\tesseract.exe'),
                    os.path.expandvars(r'%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe'),
                ]
                if os.path.exists(p)
            ),
            None,
        )
    )

    if tesseract_path:
        try:
            import pytesseract
            pytesseract.pytesseract.tesseract_cmd = tesseract_path

            tesseract_dir = os.path.dirname(tesseract_path)
            os.environ['PATH'] = f"{tesseract_dir};{os.environ['PATH']}"

            print(f"[OK] Tesseract configured at: {tesseract_path}")

            try:
                version = pytesseract.get_tesseract_version()
                print(f"[OK] Tesseract version: {version}")
            except Exception as e:
                print(f"[ERROR] Tesseract test failed: {str(e)}")

        except ImportError as e:
            print(f"[ERROR] pytesseract import error: {str(e)}")
    else:
        print(
            "[ERROR] Tesseract not found on PATH or in common install "
            "locations. Set the TESSERACT_PATH environment variable to "
            "its tesseract.exe location if it's installed elsewhere."
        )

    # ── Poppler ───────────────────────────────────────────────
    # 1) pdftoppm already on PATH
    # 2) POPPLER_PATH env var, if set
    # 3) Any C:\poppler\poppler-*\Library\bin folder (version-agnostic)
    _pdftoppm_on_path = shutil.which("pdftoppm")

    if _pdftoppm_on_path:
        POPPLER_PATH = os.path.dirname(_pdftoppm_on_path)
    elif os.environ.get("POPPLER_PATH") and os.path.exists(
        os.path.join(os.environ["POPPLER_PATH"], "pdftoppm.exe")
    ):
        POPPLER_PATH = os.environ["POPPLER_PATH"]
    else:
        _candidates = glob.glob(r'C:\poppler\poppler-*\Library\bin') + glob.glob(
            r'C:\Program Files\poppler-*\Library\bin'
        )
        POPPLER_PATH = next(
            (
                p for p in _candidates
                if os.path.exists(os.path.join(p, 'pdftoppm.exe'))
            ),
            None,
        )

    if POPPLER_PATH:
        os.environ['PATH'] = f"{POPPLER_PATH};{os.environ['PATH']}"
        print(f"[OK] Poppler configured at: {POPPLER_PATH}")
    else:
        print(
            "[ERROR] Poppler not found on PATH or in common install "
            "locations. Set the POPPLER_PATH environment variable to "
            "its Library\\bin folder if it's installed elsewhere."
        )
else:
    POPPLER_PATH = None


_PAGE_NUMBER_LINE = re.compile(
    r"^\s*(?:page\s*)?\d{1,4}(?:\s*(?:of|/)\s*\d{1,4})?\s*$|^\s*[-–]\s*\d{1,4}\s*[-–]\s*$",
    re.IGNORECASE,
)
_HEADING_LIKE = re.compile(r"^\s*(?:clause|section|article)\b|^\s*\d{1,2}[.)]\s+[A-Z]", re.IGNORECASE)
_EDGE_LINES = 3


def strip_page_furniture(pages: List[str]) -> List[str]:
    """
    Remove page numbers and running headers/footers from each page.

    Without this, "Page 2" and a running header such as "CONFIDENTIAL -
    <Bank name>" end up glued to the end of whichever clause was running
    when the page turned: they pollute the clause text the analysis and
    the chatbot read, and the viewer then highlights them as part of the
    clause.

    Only lines near the top or bottom of a page are candidates. A line is
    removed if it is a bare page number, or if the same short line (digits
    ignored, so "Page 2 of 5" and "Page 3 of 5" count as the same) sits at
    the edge of most pages. Lines that look like clause headings or end
    like a sentence are never removed, so documents that reprint content
    on every page don't lose real text.
    """
    if not pages:
        return pages
    split = [p.split("\n") for p in pages]

    def edge_positions(lines: List[str], skip: frozenset = frozenset()) -> Dict[int, set]:
        """line index -> its positions from the page edges ("t0" = first
        non-empty line, "b0" = last, ...). A running header sits in the
        same position on every page; body text that merely happens to
        repeat doesn't. On a nearly empty page a line is near both
        edges, so it gets both a top and a bottom position. Lines in
        `skip` (furniture already found) don't take up a position, so
        the line behind them counts as being at the edge."""
        filled = [i for i, line in enumerate(lines) if line.strip() and i not in skip]
        pos: Dict[int, set] = {}
        for n, i in enumerate(filled[:_EDGE_LINES]):
            pos.setdefault(i, set()).add(f"t{n}")
        for n, i in enumerate(reversed(filled[-_EDGE_LINES:])):
            pos.setdefault(i, set()).add(f"b{n}")
        return pos

    def key(line: str) -> str:
        norm = re.sub(r"\s+", " ", line).strip().lower()
        letters = len(re.findall(r"[a-z]", norm))
        digits = len(re.findall(r"\d", norm))
        # "Page 2 of 5" / "Confidential - v3" repeat with changing
        # numbers; a schedule row ("12  01/2025  1,250.00") is data, and
        # its numbers are what make it different from the next page's.
        if letters >= 3 and letters > digits:
            return re.sub(r"\d+", "#", norm)
        return norm

    def can_repeat_away(line: str) -> bool:
        s = line.strip()
        return (
            0 < len(s) <= 100
            and not _HEADING_LIKE.match(s)
            and not re.search(r"[.;:,]$", s)
        )

    repeated: set = set()
    if len(pages) >= 2:
        counts: Dict[Tuple[str, str], int] = {}
        for lines in split:
            seen = {
                (p, key(lines[i]))
                for i, tags in edge_positions(lines).items()
                if can_repeat_away(lines[i])
                for p in tags
            }
            for k in seen:
                counts[k] = counts.get(k, 0) + 1
        needed = max(2, -(-len(pages) * 6 // 10))  # on at least 60% of pages
        repeated = {k for k, c in counts.items() if c >= needed}

    def is_page_number(line: str, page_index: int) -> bool:
        m = _PAGE_NUMBER_LINE.match(line)
        if not m:
            return False
        if re.search(r"page|of|/", line, re.IGNORECASE):
            return True  # "Page 3", "3 of 10", "3/10"
        # A bare number is a page number only if it fits this page's
        # position (allowing for an unnumbered cover or two); otherwise
        # it's content, like "1250" on its own line in a table.
        number = int(re.sub(r"\D", "", line) or -1)
        return abs(number - (page_index + 1)) <= 2

    # The first copy of a repeated line is kept: a running header then
    # appears once, and a real heading repeated on every page ("REPAYMENT
    # SCHEDULE (continued)") is never lost entirely.
    #
    # PDF generators often write the header and the footer before the page
    # body, so a page can start "Agreement No. 123 / Confidential /
    # Initials ____ / Page 2" - four furniture lines, with the page number
    # beyond the first three. Once a line is found to be furniture, the
    # next line in from that edge is checked too.
    seen_repeated: set = set()
    cleaned = []
    for page_index, lines in enumerate(split):
        drop: set = set()
        furniture: set = set()  # dropped, or the kept first copy
        page_keys: set = set()
        while True:
            found = set()
            for i, tags in edge_positions(lines, frozenset(furniture)).items():
                if is_page_number(lines[i], page_index):
                    found.add(i)
                    drop.add(i)
                    continue
                if not can_repeat_away(lines[i]):
                    continue
                k = key(lines[i])
                # A running header occurs once per page. Peeling off a
                # second line with the same pattern ("Row 1 ...", "Row 2
                # ...") would eat into a table, so that stops here.
                if k in page_keys and i not in furniture:
                    continue
                if any((p, k) in repeated for p in tags):
                    found.add(i)
                    page_keys.add(k)
                    if k in seen_repeated:
                        drop.add(i)
                    seen_repeated.add(k)
            if not found - furniture:
                break
            furniture |= found
        cleaned.append("\n".join(line for i, line in enumerate(lines) if i not in drop))
    return cleaned


# A page "looks scanned" when its text layer has almost no words - fewer
# than this many letters/digits. A real text page has hundreds.
_MIN_TEXT_LAYER_CHARS = 80


def _alnum(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", text or "")


def _looks_scanned(page_text: str) -> bool:
    return len(_alnum(page_text)) < _MIN_TEXT_LAYER_CHARS


def _ocr_pdf_pages(content: bytes, page_numbers: List[int]) -> Dict[int, str]:
    """OCR the given 1-based pages. Separate so tests can replace it."""
    from pdf2image import convert_from_bytes
    import pytesseract

    out: Dict[int, str] = {}
    for number in page_numbers:
        kwargs = {"dpi": 300, "first_page": number, "last_page": number}
        if POPPLER_PATH:
            kwargs["poppler_path"] = POPPLER_PATH
        images = convert_from_bytes(content, **kwargs)
        out[number] = pytesseract.image_to_string(images[0], lang="eng") if images else ""
        print(f"OCR page {number}: {len(out[number])} characters")
    return out


def extract_text_from_file(filename: str, content: bytes) -> tuple[str, dict, List[str]]:
    """
    Extract text from file. Returns (text, metadata, pages) where metadata
    contains OCR info and pages is the per-page text (used to map each
    clause back to the page it actually appears on).

    Args:
        filename: Name of the file being processed
        content: Raw file content as bytes

    Returns:
        tuple: (extracted_text, metadata_dict, pages_list)
    """
    print(f"\n=== Processing file: {filename} ===")
    name = (filename or "").lower()
    ocr_info = {"used": False, "pages": 0, "characters": 0, "method": "text"}
    
    def log_error(msg: str, exc: Exception = None):
        """Helper function to log errors consistently."""
        error_msg = f"ERROR: {msg}"
        if exc:
            error_msg += f" - {str(exc)}"
        print(error_msg)
        return error_msg
    
    if not content:
        raise ValueError("No file content provided")
    
    if name.endswith(".pdf"):
        reader = PdfReader(BytesIO(content))
        pages = [p.extract_text() or "" for p in reader.pages]
        print(f"Direct PDF extraction got {sum(len(p.strip()) for p in pages)} characters")

        # OCR is decided page by page: a scanned page often still has a
        # little real text (a "Scanned with ..." footer, a typed cover
        # page before scanned ones), which used to keep the whole file
        # above the "has text" threshold, so its scanned pages were
        # silently lost.
        needs_ocr = [i for i, page in enumerate(pages, start=1) if _looks_scanned(page)]
        if needs_ocr:
            print(f"Pages without a usable text layer: {needs_ocr}; running OCR on them...")
            try:
                ocr_texts = _ocr_pdf_pages(content, needs_ocr)
                replaced = 0
                for number, ocr_text in ocr_texts.items():
                    if len(_alnum(ocr_text)) > len(_alnum(pages[number - 1])):
                        pages[number - 1] = ocr_text
                        replaced += 1
                ocr_characters = sum(len(ocr_texts.get(n, "")) for n in needs_ocr)
                ocr_info = {
                    "used": replaced > 0,
                    "pages": replaced,
                    "ocr_page_numbers": sorted(ocr_texts),
                    "characters": ocr_characters,
                    "method": "OCR (Tesseract)" if replaced else "text",
                }
                if replaced:
                    print(f"OCR replaced the text of {replaced} page(s)")
            except Exception as e:
                print(f"OCR extraction failed: {e}")
                import traceback
                traceback.print_exc()
                ocr_info["error"] = (
                    f"{len(needs_ocr)} page(s) look scanned but OCR failed ({e}); their text is missing."
                )

        pages = strip_page_furniture(pages)
        text = "\n\n".join(pages)
        return text, ocr_info, pages

    # Handle image files directly (JPG, PNG, etc.)
    if name.endswith(('.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.tif')):
        try:
            from PIL import Image
            import pytesseract
            
            img = Image.open(BytesIO(content))
            text = pytesseract.image_to_string(img, lang='eng')
            ocr_info = {
                "used": True,
                "pages": 1,
                "characters": len(text),
                "method": "OCR (Image)"
            }
            print(f"OCR extracted {len(text)} characters from image")
            return text, ocr_info, [text]
        except Exception as e:
            print(f"Image OCR failed: {e}")
            return "", {"used": False, "error": str(e)}, [""]
    
    # Office documents and other binary formats would otherwise be
    # "decoded" into garbage and stored as clauses.
    if name.endswith((".docx", ".doc", ".xlsx", ".xls", ".pptx", ".odt", ".rtf", ".zip")) \
            or content[:4] == b"PK\x03\x04" or b"\x00" in content[:2048]:
        raise ValueError(
            "This file type isn't supported. Save the contract as PDF (or plain text) and upload that."
        )

    # Plain text. Windows tools often save as cp1252 ("ANSI"), where
    # decoding as UTF-8 with errors ignored silently dropped characters
    # like "–" and "£" - and with them every clause heading and amount.
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = content.decode(encoding)
            return text, ocr_info, [text]
        except UnicodeDecodeError:
            continue
    text = content.decode("utf-8", errors="replace")
    return text, ocr_info, [text]


ORDINAL_WORDS = [
    "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
    "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen",
    "eighteen", "nineteen", "twenty", "twenty-one", "twenty-two", "twenty-three",
    "twenty-four", "twenty-five", "twenty-six", "twenty-seven", "twenty-eight",
    "twenty-nine", "thirty",
]
_ORDINAL_ALT = "|".join(ORDINAL_WORDS)

# Keyword-based heading, e.g. "CLAUSE ONE - PURPOSE:", "Article 1: Term",
# "Section Two - Payment". Deliberately stricter than just "keyword +
# number somewhere nearby", because that alone also matches
# mid-sentence cross-references like "as per Clause Eight below" or
# "in Section 4 of Schedule A" - which are NOT headings and would
# wrongly fragment a clause that merely refers to another one. Two
# things distinguish a real heading from a cross-reference:
#   1. The keyword itself is capitalized ("CLAUSE"/"Clause", not
#      "clause") - cross-references are usually lowercase mid-sentence.
#   2. A separator (-, –, —, :, or .) immediately follows the number,
#      then the title text begins with a capital letter - a
#      cross-reference is instead followed directly by an ordinary
#      lowercase word ("below", "of Schedule A", etc.) with no
#      separator.
_KEYWORD_HEADING = (
    r"\b(?:CLAUSE|Clause|ARTICLE|Article|SECTION|Section)\s+"
    r"(?:\d{1,3}|(?i:" + _ORDINAL_ALT + r"))"
    r"\s*[\-\u2013\u2014:.]\s*[A-Z]"
)


_SIGNATURE_START = re.compile(
    # "Signed" only as a signing statement ("Signed at Mumbai", "SIGNED
    # AND DELIVERED", "Signed:"), not a sentence that happens to start a
    # line ("Signed copies of the notice must be kept ...").
    r"^[ \t]*(?:IN\s+WITNESS\s+WHEREOF\b"
    r"|(?:SIGNED|Signed)(?=[ \t]*(?:$|[,:]|(?:at|by|on|in|and|for|this|as|sealed)\b))"
    r"|(?:SIGNATURES?|Signatures?)[ \t]*(?::|$)"
    r"|EXECUTED\b|Executed\s+(?:by|at|on|in|as)\b|WITNESS(?:ES)?\s*:|Witness(?:es)?\s*:)"
    r"|^[ \t]*By\s*:\s*_{3,}|^[ \t_]*_{5,}[ \t_]*$",
    re.MULTILINE,
)


def _cut_signature_block(clause: str) -> str:
    """The clause without a signature block that follows it. Only a line
    that starts like a signature block ("Signed at ...", "IN WITNESS
    WHEREOF", a line of underscores) ends the clause - not underscores
    inside a sentence, which are fill-in blanks."""
    m = _SIGNATURE_START.search(clause, 1)
    if not m or m.start() < 40:
        return clause
    return clause[: m.start()].rstrip()


def split_document(text: str) -> Tuple[Optional[str], List[str]]:
    """
    Split a contract's text into (header, clauses).

    header: everything before the first clause heading - title, parties,
      lender/borrower, financed amount, recitals - or None when the
      document starts straight with a clause or has no headings. It is
      real, citable document text (searchable, and "jump to" can
      highlight it), but it is not an operative clause: it creates no
      obligation, so it must never be risk-classified, policy-scored or
      counted as a clause. Callers keep it separate from the clause list.
    clauses: the operative clauses, in document order.
    """
    if not text:
        return None, []
    # Normalize line endings
    t = re.sub(r"\r\n?", "\n", text).strip()
    t = re.sub(r"\n{3,}", "\n\n", t)

    # Primary strategy: split right before clause headings. Two heading
    # conventions are recognized:
    #   1. Numbered ALL-CAPS headings, e.g. "2. TERM",
    #      "18. SIGNATURES AND CONSENT" - the most common convention.
    #      Requires ALL-CAPS words immediately after the number so real
    #      body text containing a stray number isn't mistaken for a
    #      heading.
    #   2. Keyword + number/spelled-out-ordinal headings (see
    #      _KEYWORD_HEADING above), e.g. "CLAUSE ONE - PURPOSE",
    #      "Article 1: Term", "Section Two - Payment".
    # Both are zero-width lookaheads so the split works whether or not
    # the PDF's extracted text preserves a newline before the heading
    # (real-world PDF text extraction often doesn't).
    HEADER_RE = re.compile(
        # (?<![\d.,]) stops "$45,892.00. CLAUSE ONE" being read as a
        # numbered heading "00. CLAUSE", which cut the cents off amounts.
        r"(?<![\d.,])(?=\b\d{1,2}[\.\)]\s+[A-Z]{2,}(?:[\s&/\-]+[A-Z]{2,}){0,6}\b)"
        r"|(?=" + _KEYWORD_HEADING + r")"
    )
    parts = HEADER_RE.split(t)
    parts = [p.strip() for p in parts if p and p.strip()]
 
    # If headings were found, the first chunk is whatever came before the
    # very first heading (document title, party names, recitals, etc.)
    # - unless the document has no preamble and a heading is the first
    # thing in the text. Drop it in the former case; it isn't a clause.
    FIRST_HEADING_RE = re.compile(
        r"^\d{1,2}[\.\)]\s+[A-Z]{2,}"
        r"|^" + _KEYWORD_HEADING
    )
    header: Optional[str] = None
    if len(parts) > 1 and not FIRST_HEADING_RE.match(parts[0]):
        header = re.sub(r"\s+", " ", parts[0]).strip()
        if len(header) < 20:
            header = None  # just a title - nothing worth citing
        parts = parts[1:]

    # Fallback: if that found hardly any headings (e.g. a document that
    # doesn't use ALL-CAPS numbered section titles), split on blank-line
    # paragraph breaks instead.
    if len(parts) <= 1:
        collapsed = re.sub(r"(?<!\n)\n(?!\n)", " ", t)
        parts = re.split(r"\n{2,}", collapsed)
        parts = [p.strip() for p in parts if p and p.strip()]

    # The signature block after the last clause ("IN WITNESS WHEREOF",
    # "Signed at ...", lines of underscores) is not part of that clause.
    # It used to stay attached, and the "_____" noise rule below then
    # threw the whole clause away - so every signed contract lost its
    # last clause (usually jurisdiction).
    heading_start = re.compile(r"^\d{1,2}[\.\)]\s+[A-Z]{2,}|^" + _KEYWORD_HEADING)
    is_clause = [bool(heading_start.match(p)) for p in parts]
    parts = [_cut_signature_block(p) if clause else p for p, clause in zip(parts, is_clause)]

    # Within each part, collapse remaining internal single newlines
    # (mid-sentence line wraps) into spaces, and tidy up whitespace.
    parts = [re.sub(r"(?<!\n)\n(?!\n)", " ", p) for p in parts]
    parts = [re.sub(r"\s{2,}", " ", p).strip() for p in parts]

    # Filter out very short fragments
    keep = [len(p) >= 40 for p in parts]
    is_clause = [c for c, k in zip(is_clause, keep) if k]
    refined = [p for p, k in zip(parts, keep) if k]

    # Remove boilerplate headers/footers/signature blocks/page numbers
    NOISE_PATTERNS = [
        r"^service agreement\b",
        r"\bagreement is made between\b",
        r"^signatures?:?\b",
        r"^signed by\b",
        r"representative:\s*_{3,}",
        r"_{5,}",
        r"^witness(ed)?\b",
        r"^page\s+\d+(\s+of\s+\d+)?\s*$",
        r"^\d+\s*$",
        r"^confidential\b\s*$",
    ]
    def is_noise(s: str) -> bool:
        t = (s or "").strip().lower()
        for pat in NOISE_PATTERNS:
            if re.search(pat, t, flags=re.IGNORECASE):
                return True
        return False
    # A part that starts with a clause heading is a clause, even if it
    # contains a fill-in blank ("Account no.: ________").
    refined = [c for c, clause in zip(refined, is_clause) if clause or not is_noise(c)]

    # Deduplicate identical/near-identical clauses. Some PDF generators
    # reprint the same full clause list on every page (a source-document
    # artifact, not something clause-splitting can prevent), which would
    # otherwise multiply every clause by however many times it's
    # repeated. Compare just the normalized opening portion of each
    # clause rather than the full text, since the last repetition often
    # has trailing content (e.g. a signature block) merged onto it,
    # which would otherwise make it fail an exact-match comparison and
    # slip through as a false "new" clause.
    def _dedup_key(clause: str) -> str:
        normalized = re.sub(r"\s+", " ", clause).strip().lower()
        return normalized[:80]

    seen_keys = set()
    deduped: List[str] = []
    for clause in refined:
        key = _dedup_key(clause)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        deduped.append(clause)
    refined = deduped

    return header, refined


def split_into_clauses(text: str) -> List[str]:
    """Operative clauses only (see split_document)."""
    return split_document(text)[1]


_WORD_RE = re.compile(r"[a-z0-9]{3,}")


def coverage_report(text: str, header: Optional[str], clauses: List[str]) -> Dict[str, Any]:
    """
    Check that splitting didn't silently lose document text.

    Compares the distinct words of the source with the distinct words
    kept in header + clauses. Distinct words (not character counts)
    make this robust to PDFs that repeat the same page, which the
    splitter deliberately de-duplicates. Removed boilerplate (page
    numbers, signature lines) costs very little. A low ratio means
    real content was dropped - e.g. an unrecognized heading style made
    most of a document fall outside the clauses - and the analysis for
    that document should not be trusted until it's looked at.
    """
    source_words = set(_WORD_RE.findall((text or "").lower()))
    kept = " ".join(([header] if header else []) + list(clauses)).lower()
    kept_words = set(_WORD_RE.findall(kept))
    if not source_words:
        return {"ratio": 1.0, "ok": True, "missing_sample": []}
    missing = sorted(source_words - kept_words)
    ratio = 1 - len(missing) / len(source_words)
    return {
        "ratio": round(ratio, 3),
        "ok": ratio >= 0.95,
        "missing_sample": missing[:20],
    }


# ---------------------------------------------------------------- facts
#
# Labeled fields ("FINANCED AMOUNT: $45,892.00", "LENDER: ...") are read
# straight from the document text. When a document labels a value, the
# label is the authority - an LLM reading is only used when there is no
# label, and even then must be found verbatim in the text (see
# llm_agent.ground_metadata).

_CURRENCY_SYMBOLS = {
    "$": "USD", "US$": "USD", "₹": "INR", "€": "EUR", "£": "GBP", "Rs.": "INR", "Rs": "INR",
    "R$": "BRL", "C$": "CAD", "CA$": "CAD", "A$": "AUD", "AU$": "AUD", "S$": "SGD", "¥": "JPY",
}
_CURRENCY_CODES = r"INR|USD|EUR|GBP|BRL|CAD|AUD|SGD|AED|JPY|CHF|CNY|ZAR|NZD|HKD|MXN"
# Written amounts in the grouping styles contracts use: 1,203,432.00 (US),
# 4,58,920.00 (Indian), 45.892,00 and 45 892,00 (European), 1203432.
_AMOUNT_NUM = (
    r"\d{1,2}(?:,\d{2})+,\d{3}(?:\.\d{1,2})?"          # 4,58,920.00 (Indian)
    r"|\d{1,3}(?:,\d{3})+(?:\.\d{1,3})?"                # 1,203,432.00
    r"|\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?"                # 45.892,00
    r"|\d{1,3}(?:[\u00a0\u202f]\d{3})+(?:[.,]\d{1,2})?"  # 45 892,00 (non-breaking space)
    r"|\d{1,3}(?: \d{3})+,\d{1,2}"                      # 45 892,00 (space, decimal comma)
    r"|\d+(?:[.,]\d{1,2})?"
)
# A plain space alone is not a separator: "$45,892 360 monthly" is two
# numbers, not 45,892,360.
_MONEY_RE = re.compile(
    r"(?P<cur>US\$|R\$|CA\$|C\$|AU\$|A\$|S\$|\$|₹|€|£|¥|Rs\.?|" + _CURRENCY_CODES + r")\s?"
    r"(?P<num>" + _AMOUNT_NUM + r")(?![\d])"
    r"|(?<![\d.,])(?P<num2>" + _AMOUNT_NUM + r")\s?(?P<cur2>(?:" + _CURRENCY_CODES + r")\b|€|₹|£)"
)
_AMOUNT_LABELS = (
    r"FINANCED\s+AMOUNT|AMOUNT\s+FINANCED|LOAN\s+AMOUNT|PRINCIPAL(?:\s+AMOUNT)?|"
    r"TOTAL\s+CONTRACT\s+VALUE|CONTRACT\s+VALUE|TOTAL\s+VALUE|"
    r"CONTRACT\s+PRICE|TOTAL\s+(?:FEES?|PRICE|AMOUNT)|PURCHASE\s+PRICE"
)
_PARTY_LABELS = {
    "lender_name": r"LENDER|BANK|CREDITOR",
    "customer_name": r"BORROWER|CUSTOMER|CLIENT|DEBTOR",
}
# Where the text after a label stops being about that label.
# Where the text after a label stops being about that label: a clause
# heading, an ALL-CAPS label ("LENDER:"), a known field label in any case
# ("Address:", "Lender:", "Dated:"), or any "Label:" at the start of a line.
# Not just any "Word:" - a party's own name can contain one ("Trading As
# Acme: Retail").
_FIELD_LABELS = (
    r"address|residing|borrower|co-borrower|lender|bank|creditor|customer|client|debtor|guarantor|"
    r"amount(?:\s+financed)?|financed\s+amount|loan\s+amount|principal(?:\s+amount)?|tenure|term|"
    r"date|dated|effective\s+date|interest(?:\s+rate)?|rate|ssn|ein|pan|tax\s+id|cnpj|cpf|email|e-mail|"
    r"phone|tel|telephone|mobile|contact|signature|witness|place|attn|attention|c/o|care\s+of"
)
_NAME_BOUNDARY = re.compile(
    r"\bCLAUSE\b|\bSECTION\b|\bARTICLE\b"
    r"|(?<![A-Za-z])(?i:" + _FIELD_LABELS + r")[ \t]*:(?!//)"
    r"|(?m:^)[ \t]*[A-Z][A-Za-z]*(?:[ \t]+[A-Za-z]+){0,3}[ \t]*:(?!//)"
)
# For amounts, also any ALL-CAPS label ("TERM:", "RATE OF INTEREST:"). Not
# for names: in "JOHN SMITH ADDRESS:" it would start at "SMITH".
_NEXT_SECTION = re.compile(
    _NAME_BOUNDARY.pattern + r"|\b[A-Z]{3,}(?:[ \t]+[A-Z]{2,}){0,3}[ \t]*:(?!//)"
)


def _currency_code(raw: str) -> str:
    raw = (raw or "").strip()
    return _CURRENCY_SYMBOLS.get(raw, raw.upper().rstrip("."))


def find_money_amounts(text: str) -> List[Dict[str, Any]]:
    """Every currency amount written in the text."""
    from .schemas import _number_from_digits

    found = []
    for m in _MONEY_RE.finditer(text or ""):
        num = m.group("num") or m.group("num2")
        cur = m.group("cur") or m.group("cur2")
        if re.fullmatch(r"\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?", num or ""):
            # "EUR 45.892" / "45.892,00": in a document, dot-grouped figures
            # next to a currency are European thousands.
            value = float(num.replace(".", "").replace(",", "."))
        else:
            value = _number_from_digits(num or "")
        if value is None:
            continue
        found.append({"value": value, "currency": _currency_code(cur), "text": m.group(0).strip()})
    return found


# Abbreviations whose trailing dot is part of a name ("Mr. John Smith",
# "St. George Bank", "J.P. Morgan"), and company suffixes that end one.
_NAME_ABBREVIATIONS = {"mr", "mrs", "ms", "dr", "st", "prof", "sr", "jr", "mt", "ste", "messrs", "no"}
_COMPANY_SUFFIX = re.compile(r"(?:inc|ltd|llc|llp|corp|co|plc|gmbh|s\.a|n\.a|pvt)$", re.IGNORECASE)
_NAME_CONTINUES = re.compile(
    r"&|(?:private|pvt|limited|ltd|llc|llp|inc|incorporated|corporation|corp|company|co|gmbh|plc|"
    r"s\.a|trust|bank|holdings|group|partners)\b",
    re.IGNORECASE,
)
# Words that end a party name when written in lower case or ALL CAPS
# ("..., residing at", "REGISTERED UNDER") - but not in Title Case, where
# they're part of a name ("Having Industries Ltd", "Smith With Partners").
_NAME_STOP_WORDS = [
    "residing", "registered", "headquartered", "holder", "domiciled", "located", "incorporated",
    "having", "with", "whose", "represented", "hereinafter", "herein",
]
_NAME_STOP = re.compile(
    r"[,;(\n]|:(?!//)|\.(?=\s|$)|(?<![A-Za-z])(?:"
    + "|".join(w + "|" + w.upper() for w in _NAME_STOP_WORDS)
    + r")(?![A-Za-z])"
)


def _name_after_label(rest: str) -> Optional[str]:
    """The party name at the start of `rest` (the text right after
    'BORROWER:'), ending at a comma, a descriptive phrase, or a
    sentence-ending full stop - but not at the dot of "Mr." or "J.P."."""
    # From position 1: the value itself ("John Smith ...") must not count
    # as a line-start label.
    boundary = _NAME_BOUNDARY.search(rest, 1)
    rest = rest[: boundary.start()] if boundary else rest
    rest = rest[:120]
    for stop in _NAME_STOP.finditer(rest):
        if stop.group(0) == "\n":
            following = rest[stop.end():].lstrip(" \t")
            nxt = following[:1]
            if nxt and (nxt.islower() or re.match(_NAME_CONTINUES.pattern + r"(?![A-Za-z])", following, re.IGNORECASE)) \
                    and not re.match(r"[A-Za-z ]{1,30}:", following):
                continue  # "Sunrise Solar\nPrivate Limited" - the name goes on
        if stop.group(0) == ".":
            word = re.search(r"([A-Za-z]+)$", rest[: stop.start()])
            token = (word.group(1) if word else "").lower()
            if token in _NAME_ABBREVIATIONS or len(token) == 1:
                continue  # "Mr." / "J." - part of the name
            if _COMPANY_SUFFIX.search(rest[: stop.start()]):
                following = rest[stop.end():].lstrip()
                if re.match(r"(?:ltd|limited|inc|llc|llp|plc|corp|co)\b", following, re.IGNORECASE):
                    continue  # "Acme Pvt. Ltd.", "Johnson & Co. Ltd." - the suffix goes on
                return rest[: stop.end()].strip().rstrip(".")  # "Acme Inc." ends the name
        name = rest[: stop.start()].strip()
        return name or None
    return rest.strip() or None


def extract_labeled_facts(text: str) -> Dict[str, Any]:
    """
    Values the document states under an explicit label, e.g.
    'FINANCED AMOUNT: $45,892.00.', 'LENDER: FINANCIAL BANK OF AMERICA Inc., ...'.
    Only the first occurrence of each label is used. Keys are absent
    when the document has no such label.
    """
    t = re.sub(r"\s+", " ", text or "")
    # Party names end at a line break, so keep line breaks for them.
    t_lines = re.sub(r"[ \t\r\f\v]+", " ", text or "")
    facts: Dict[str, Any] = {}

    m = re.search(r"\b(?P<label>" + _AMOUNT_LABELS + r")\s*[:\-]\s*", t, re.IGNORECASE)
    if m:
        # Up to the next clause or label, so an amount written out in
        # words with the figure after it ("Forty-five thousand ...
        # dollars ($45,892.00)") is read whole, never cut mid-number.
        rest = t[m.end(): m.end() + 300]
        boundary = _NEXT_SECTION.search(rest, 1)
        rest = rest[: boundary.start()] if boundary else rest
        amounts = find_money_amounts(rest)
        if amounts:
            facts["contract_value"] = amounts[0]["value"]
            facts["currency"] = amounts[0]["currency"]
            facts["contract_value_text"] = amounts[0]["text"]
            facts["contract_value_label"] = re.sub(r"\s+", " ", m.group("label").upper())

    for key, labels in _PARTY_LABELS.items():
        m = re.search(r"(?:^|[\s.;])(?:" + labels + r")[ \t]*:[ \t]*", t_lines, re.IGNORECASE)
        if not m:
            continue
        name = _name_after_label(t_lines[m.end():])
        if not name:
            continue
        name = re.sub(r"\s+", " ", name).strip().rstrip(".,;: ")
        if len(name) < 2 or len(name) > 80:
            continue
        if name.lower() in {"the bank", "the lender", "the borrower", "the client", "the customer"}:
            continue
        facts[key] = name
    return facts

def assign_clause_pages(clauses: List[str], pages: List[str]) -> List[int]:
    """
    For each clause, figure out which page (1-indexed) it actually
    appears on, by searching the per-page text for a distinctive
    snippet of the clause's opening words. Falls back to the last
    known page (or page 1) if no page's text contains a match, so
    every clause always gets a usable page number.
    """
    def normalize(s: str) -> str:
        return re.sub(r"\s+", " ", (s or "")).strip().lower()

    normalized_pages = [normalize(p) for p in pages]
    page_numbers: List[int] = []
    last_page = 1

    for clause in clauses:
        norm_clause = normalize(clause)
        snippet = norm_clause[:80]

        found_page = None
        search_order = list(range(last_page - 1, len(normalized_pages))) + list(
            range(0, last_page - 1)
        )

        for idx in search_order:
            if len(snippet) >= 20 and snippet in normalized_pages[idx]:
                found_page = idx + 1
                break

        if found_page is None:
            shorter = norm_clause[:30]
            for idx in search_order:
                if len(shorter) >= 12 and shorter in normalized_pages[idx]:
                    found_page = idx + 1
                    break

        if found_page is None:
            found_page = last_page

        page_numbers.append(found_page)
        last_page = found_page

    return page_numbers

DATE_PATTERNS = [
    r"\b(?:\d{1,2}[\-/]\d{1,2}[\-/]\d{2,4})\b",
    r"\b(?:\d{4}[\-/]\d{1,2}[\-/]\d{1,2})\b",
    r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\s+\d{1,2},\s+\d{4}\b",
]

RISKY_WORDS = [
    "indemnify","indemnification","penalty","termination for cause","liquidated damages",
    "hold harmless","unlimited liability","warranty disclaimer","non-compete","exclusive",
    "non-solicitation","arbitration","governing law","confidentiality breach","data breach",
]


def extract_metadata(clause_text: str) -> Dict[str, Any]:
    text = clause_text or ""
    dates = []
    for pat in DATE_PATTERNS:
        dates.extend(re.findall(pat, text, flags=re.IGNORECASE))

    risky_hits = [w for w in RISKY_WORDS if re.search(re.escape(w), text, flags=re.IGNORECASE)]

    # Simple heuristic for renewal/expiry
    expiry_hint = None
    if re.search(r"expiry|expiration|term ends|valid until|renewal", text, flags=re.IGNORECASE):
        expiry_hint = True

    return {
        "dates_found": dates[:5],
        "risky_terms": risky_hits[:10],
        "expiry_related": bool(expiry_hint),
        "length": len(text),
    }
    