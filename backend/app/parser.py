import re
from typing import List, Dict, Any
from pypdf import PdfReader
from io import BytesIO
import os
import platform


# ============================================================
# Configure Tesseract and Poppler
# ============================================================

TESSERACT_PATH = None
POPPLER_PATH = None

if platform.system() == "Windows":
    print("Configuring for Windows...")

    # --------------------------------------------------------
    # Tesseract configuration
    # --------------------------------------------------------
    TESSERACT_PATH = (
        r"C:\Users\RajeshRobin\AppData\Local\Programs"
        r"\Tesseract-OCR\tesseract.exe"
    )

    if os.path.exists(TESSERACT_PATH):
        try:
            import pytesseract

            # Tell pytesseract exactly where Tesseract is
            pytesseract.pytesseract.tesseract_cmd = TESSERACT_PATH

            # Add Tesseract directory to PATH for this process
            tesseract_dir = os.path.dirname(TESSERACT_PATH)

            os.environ["PATH"] = (
                f"{tesseract_dir};"
                f"{os.environ.get('PATH', '')}"
            )

            print(
                f"[OK] Tesseract configured at: "
                f"{TESSERACT_PATH}"
            )

            # Test Tesseract
            try:
                version = pytesseract.get_tesseract_version()

                print(
                    f"[OK] Tesseract version: {version}"
                )

                print(
                    "[OK] Tesseract is now available in PATH"
                )

            except Exception as e:
                print(
                    f"[ERROR] Tesseract test failed: {e}"
                )

        except ImportError as e:
            print(
                f"[ERROR] pytesseract import error: {e}"
            )

    else:
        print(
            f"[ERROR] Tesseract not found at: "
            f"{TESSERACT_PATH}"
        )

    # --------------------------------------------------------
    # Poppler configuration
    # --------------------------------------------------------
    POPPLER_PATH = (
        r"C:\Users\RajeshRobin\AppData\Local\Microsoft\WinGet"
        r"\Packages\oschwartz10612.Poppler_Microsoft.Winget.Source_8wekyb3d8bbwe"
        r"\poppler-25.07.0\Library\bin"
    )

    if os.path.exists(POPPLER_PATH):

        # Add Poppler to PATH for this process
        os.environ["PATH"] = (
            f"{POPPLER_PATH};"
            f"{os.environ.get('PATH', '')}"
        )

        print(
            f"[OK] Poppler configured at: "
            f"{POPPLER_PATH}"
        )

        # Test pdftoppm
        pdftoppm_path = os.path.join(
            POPPLER_PATH,
            "pdftoppm.exe"
        )

        if os.path.exists(pdftoppm_path):
            print(
                f"[OK] Found pdftoppm at: "
                f"{pdftoppm_path}"
            )
        else:
            print(
                f"[ERROR] pdftoppm not found at: "
                f"{pdftoppm_path}"
            )

    else:
        print(
            f"[ERROR] Poppler not found at: "
            f"{POPPLER_PATH}"
        )

        POPPLER_PATH = None

else:
    print(
        "Non-Windows OS detected; "
        "using system Tesseract/Poppler."
    )


# ============================================================
# Extract text from files
# ============================================================

def extract_text_from_file(
    filename: str,
    content: bytes
) -> tuple[str, dict]:
    """
    Extract text from a file.

    Returns:
        tuple[str, dict]:
            Extracted text and OCR metadata.
    """

    print(
        f"\n=== Processing file: {filename} ==="
    )

    name = (filename or "").lower()

    ocr_info = {
        "used": False,
        "pages": 0,
        "characters": 0,
        "method": "text"
    }

    # --------------------------------------------------------
    # Validate content
    # --------------------------------------------------------

    if not content:
        raise ValueError(
            "No file content provided"
        )

    # ========================================================
    # PDF
    # ========================================================

    if name.endswith(".pdf"):

        try:
            reader = PdfReader(
                BytesIO(content)
            )

            pages = [
                page.extract_text() or ""
                for page in reader.pages
            ]

            text = "\n\n".join(pages)

            original_length = len(
                text.strip()
            )

            print(
                f"Direct PDF extraction got "
                f"{original_length} characters"
            )

        except Exception as e:

            print(
                f"PDF text extraction failed: {e}"
            )

            text = ""

            original_length = 0

        # ----------------------------------------------------
        # OCR fallback for scanned/image PDFs
        # ----------------------------------------------------

        if original_length < 100:

            print(
                "Text too short, attempting OCR extraction..."
            )

            try:

                from pdf2image import convert_from_bytes
                import pytesseract

                # Make sure Tesseract is configured
                if TESSERACT_PATH:

                    pytesseract.pytesseract.tesseract_cmd = (
                        TESSERACT_PATH
                    )

                # ------------------------------------------------
                # Convert PDF pages to images
                # ------------------------------------------------

                print(
                    f"Converting PDF to images using "
                    f"Poppler at: {POPPLER_PATH}"
                )

                if POPPLER_PATH:

                    images = convert_from_bytes(
                        content,
                        dpi=300,
                        poppler_path=POPPLER_PATH
                    )

                else:

                    images = convert_from_bytes(
                        content,
                        dpi=300
                    )

                print(
                    f"Converted PDF to "
                    f"{len(images)} images"
                )

                # ------------------------------------------------
                # OCR each page
                # ------------------------------------------------

                ocr_pages = []

                for i, img in enumerate(
                    images,
                    1
                ):

                    print(
                        f"Running OCR on page {i}..."
                    )

                    ocr_text = (
                        pytesseract.image_to_string(
                            img,
                            lang="eng"
                        )
                    )

                    if ocr_text.strip():

                        ocr_pages.append(
                            ocr_text
                        )

                        print(
                            f"Page {i}: "
                            f"Extracted "
                            f"{len(ocr_text)} "
                            f"characters"
                        )

                # ------------------------------------------------
                # Combine OCR results
                # ------------------------------------------------

                if ocr_pages:

                    text = "\n\n".join(
                        ocr_pages
                    )

                    ocr_info = {
                        "used": True,
                        "pages": len(images),
                        "characters": len(text),
                        "method": "OCR (Tesseract)"
                    }

                    print(
                        f"OCR extracted "
                        f"{len(text)} total characters "
                        f"from {len(images)} pages"
                    )

                else:

                    print(
                        "OCR produced no text"
                    )

            except Exception as e:

                print(
                    f"OCR extraction failed: {e}"
                )

                import traceback

                traceback.print_exc()

                ocr_info["error"] = str(e)

        return text, ocr_info

    # ========================================================
    # Image files
    # ========================================================

    if name.endswith(
        (
            ".jpg",
            ".jpeg",
            ".png",
            ".bmp",
            ".tiff",
            ".tif"
        )
    ):

        try:

            from PIL import Image
            import pytesseract

            # Make sure Tesseract is configured
            if TESSERACT_PATH:

                pytesseract.pytesseract.tesseract_cmd = (
                    TESSERACT_PATH
                )

            # Open image
            img = Image.open(
                BytesIO(content)
            )

            # OCR
            text = pytesseract.image_to_string(
                img,
                lang="eng"
            )

            ocr_info = {
                "used": True,
                "pages": 1,
                "characters": len(text),
                "method": "OCR (Image)"
            }

            print(
                f"OCR extracted "
                f"{len(text)} characters "
                f"from image"
            )

            return text, ocr_info

        except Exception as e:

            print(
                f"Image OCR failed: {e}"
            )

            return "", {
                "used": False,
                "error": str(e)
            }

    # ========================================================
    # Plain text / other files
    # ========================================================

    try:

        text = content.decode(
            "utf-8",
            errors="ignore"
        )

        return text, ocr_info

    except Exception:

        text = content.decode(
            errors="ignore"
        )

        return text, ocr_info


# ============================================================
# Split text into clauses
# ============================================================

def split_into_clauses(
    text: str
) -> List[str]:

    if not text:
        return []

    # --------------------------------------------------------
    # Normalize line endings
    # --------------------------------------------------------

    t = re.sub(
        r"\r\n?",
        "\n",
        text
    ).strip()

    # --------------------------------------------------------
    # Normalize multiple blank lines
    # --------------------------------------------------------

    t = re.sub(
        r"\n{3,}",
        "\n\n",
        t
    )

    # --------------------------------------------------------
    # Smart Paragraph Breaking for Inline Clauses
    # --------------------------------------------------------

    # 1. Promote newlines before numbered lists to double newlines
    t = re.sub(
        r"\n\s*(\d+[\.)]\s+[A-Z])", 
        r"\n\n\1", 
        t
    )
    
    # 2. Insert double newlines before inline numbered lists (following a period)
    t = re.sub(
        r"(?<=\.)\s+(\d+[\.)]\s+[A-Z])", 
        r"\n\n\1", 
        t
    )

    # --------------------------------------------------------
    # Replace single newlines with spaces
    # --------------------------------------------------------

    t = re.sub(
        r"(?<!\n)\n(?!\n)",
        " ",
        t
    )

    # --------------------------------------------------------
    # Split by:
    #   1. Paragraph breaks (double newlines)
    #   2. Heading-like lines
    # --------------------------------------------------------

    parts = re.split(
        r"\n{2,}|(?:\n(?=[A-Z][A-Za-z ]{3,}:))",
        t
    )

    parts = [
        p.strip()
        for p in parts
        if p and p.strip()
    ]

    # --------------------------------------------------------
    # Remove very short fragments (Keep paragraphs intact!)
    # --------------------------------------------------------

    refined = [
        p
        for p in parts
        if len(p) >= 40
    ]

    # ========================================================
    # Remove boilerplate / noise
    # ========================================================

    NOISE_PATTERNS = [

        r"^service agreement\b",

        r"\bagreement is made between\b",

        r"^signatures?:?\b",

        r"^signed by\b",

        r"representative:\s*_{3,}",

        r"_{5,}",

        r"^witness(ed)?\b",
    ]

    def is_noise(
        value: str
    ) -> bool:

        value = (
            value or ""
        ).strip().lower()

        for pattern in NOISE_PATTERNS:

            if re.search(
                pattern,
                value,
                flags=re.IGNORECASE
            ):
                return True

        return False

    refined = [
        clause
        for clause in refined
        if not is_noise(clause)
    ]

    return refined


# ============================================================
# Date patterns
# ============================================================

DATE_PATTERNS = [

    # 01/02/2026
    r"\b(?:\d{1,2}[\-/]\d{1,2}[\-/]\d{2,4})\b",

    # 2026-02-01
    r"\b(?:\d{4}[\-/]\d{1,2}[\-/]\d{1,2})\b",

    # January 1, 2026
    r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)"
    r"[a-z]*\s+\d{1,2},\s+\d{4}\b",
]


# ============================================================
# Risky contract terms
# ============================================================

RISKY_WORDS = [

    "indemnify",
    "indemnification",
    "penalty",
    "termination for cause",
    "liquidated damages",
    "hold harmless",
    "unlimited liability",
    "warranty disclaimer",
    "non-compete",
    "exclusive",
    "non-solicitation",
    "arbitration",
    "governing law",
    "confidentiality breach",
    "data breach",
]


# ============================================================
# Extract clause metadata
# ============================================================

def extract_metadata(
    clause_text: str
) -> Dict[str, Any]:

    text = clause_text or ""

    # --------------------------------------------------------
    # Find dates
    # --------------------------------------------------------

    dates = []

    for pattern in DATE_PATTERNS:

        dates.extend(
            re.findall(
                pattern,
                text,
                flags=re.IGNORECASE
            )
        )

    # --------------------------------------------------------
    # Find risky terms
    # --------------------------------------------------------

    risky_hits = [

        word

        for word in RISKY_WORDS

        if re.search(
            re.escape(word),
            text,
            flags=re.IGNORECASE
        )
    ]

    # --------------------------------------------------------
    # Detect expiry / renewal language
    # --------------------------------------------------------

    expiry_hint = None

    if re.search(
        r"expiry|expiration|term ends|valid until|renewal",
        text,
        flags=re.IGNORECASE
    ):
        expiry_hint = True

    # --------------------------------------------------------
    # Return metadata
    # --------------------------------------------------------

    return {

        "dates_found": dates[:5],

        "risky_terms": risky_hits[:10],

        "expiry_related": bool(
            expiry_hint
        ),

        "length": len(text),
    }
