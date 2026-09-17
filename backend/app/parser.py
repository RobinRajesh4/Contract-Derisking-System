import re
from typing import List, Dict, Any
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
        text = "\n\n".join(pages)
        original_length = len(text.strip())

        print(f"Direct PDF extraction got {original_length} characters")

        # If extracted text is too short (likely image-based PDF), try OCR
        if original_length < 100:
            print("Text too short, attempting OCR extraction...")
            try:
                from pdf2image import convert_from_bytes
                import pytesseract

                # Convert PDF to images
                print(f"Converting PDF to images using Poppler at: {POPPLER_PATH}")
                if POPPLER_PATH:
                    images = convert_from_bytes(content, dpi=300, poppler_path=POPPLER_PATH)
                else:
                    images = convert_from_bytes(content, dpi=300)

                print(f"Converted PDF to {len(images)} images")

                # Extract text from each image using OCR
                ocr_pages = []
                for i, img in enumerate(images, 1):
                    print(f"Running OCR on page {i}...")
                    ocr_text = pytesseract.image_to_string(img, lang='eng')
                    # Always append (even if empty) so page indices stay
                    # aligned 1:1 with the real PDF page numbers.
                    ocr_pages.append(ocr_text)
                    if ocr_text.strip():
                        print(f"Page {i}: Extracted {len(ocr_text)} characters")

                if any(p.strip() for p in ocr_pages):
                    text = "\n\n".join(ocr_pages)
                    pages = ocr_pages
                    ocr_info = {
                        "used": True,
                        "pages": len(images),
                        "characters": len(text),
                        "method": "OCR (Tesseract)"
                    }
                    print(f"OCR extracted {len(text)} total characters from {len(images)} pages")
                else:
                    print("OCR produced no text")

            except Exception as e:
                print(f"OCR extraction failed: {e}")
                import traceback
                traceback.print_exc()
                ocr_info["error"] = str(e)

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
    
    # Treat everything else as text
    try:
        text = content.decode("utf-8", errors="ignore")
        return text, ocr_info, [text]
    except Exception:
        text = content.decode(errors="ignore")
        return text, ocr_info, [text]


def split_into_clauses(text: str) -> List[str]:
    if not text:
        return []
    # Normalize line endings
    t = re.sub(r"\r\n?", "\n", text).strip()
    t = re.sub(r"\n{3,}", "\n\n", t)

    # Primary strategy: split right before numbered ALL-CAPS clause
    # headings (e.g. "2. TERM", "18. SIGNATURES AND CONSENT"), which is
    # how most contracts label their sections. This is done with a
    # zero-width lookahead directly on the pattern itself, so it works
    # whether or not the PDF's extracted text preserves a newline or
    # blank line before the heading (real-world PDF text extraction
    # often doesn't).
    HEADER_RE = re.compile(
        r"(?=\b\d{1,2}[\.\)]\s+[A-Z]{2,}(?:[\s&/\-]+[A-Z]{2,}){0,6}\b)"
    )
    parts = HEADER_RE.split(t)
    parts = [p.strip() for p in parts if p and p.strip()]

    # If headings were found, the first chunk is whatever came before the
    # very first heading (document title, party names, recitals, etc.)
    # - unless the document has no preamble and a heading is the first
    # thing in the text. Drop it in the former case; it isn't a clause.
    FIRST_HEADING_RE = re.compile(r"^\d{1,2}[\.\)]\s+[A-Z]{2,}")
    if len(parts) > 1 and not FIRST_HEADING_RE.match(parts[0]):
        parts = parts[1:]

    # Fallback: if that found hardly any headings (e.g. a document that
    # doesn't use ALL-CAPS numbered section titles), split on blank-line
    # paragraph breaks instead.
    if len(parts) <= 1:
        collapsed = re.sub(r"(?<!\n)\n(?!\n)", " ", t)
        parts = re.split(r"\n{2,}", collapsed)
        parts = [p.strip() for p in parts if p and p.strip()]

    # Within each part, collapse remaining internal single newlines
    # (mid-sentence line wraps) into spaces, and tidy up whitespace.
    parts = [re.sub(r"(?<!\n)\n(?!\n)", " ", p) for p in parts]
    parts = [re.sub(r"\s{2,}", " ", p).strip() for p in parts]

    # Filter out very short fragments
    refined = [p for p in parts if len(p) >= 40]

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
    refined = [c for c in refined if not is_noise(c)]

    return refined

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
