import re
from typing import List, Dict, Any
from pypdf import PdfReader
from io import BytesIO
import os
import platform

# Configure Tesseract and Poppler paths for Windows
if platform.system() == 'Windows':
    print("Configuring for Windows...")
    
    # Tesseract configuration
    tesseract_path = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
    if os.path.exists(tesseract_path):
        try:
            import pytesseract
            # Set the path to tesseract executable
            pytesseract.pytesseract.tesseract_cmd = tesseract_path
            
            # Also add Tesseract to system PATH for this session
            os.environ['PATH'] = f"C:\\Program Files\\Tesseract-OCR;{os.environ['PATH']}"
            
            print(f"[OK] Tesseract configured at: {tesseract_path}")
            
            # Test Tesseract
            try:
                version = pytesseract.get_tesseract_version()
                print(f"[OK] Tesseract version: {version}")
                print(f"[OK] Tesseract is now available in PATH")
            except Exception as e:
                print(f"[ERROR] Tesseract test failed: {str(e)}")
                print("Please ensure Tesseract is properly installed at the specified path.")
                
        except ImportError as e:
            print(f"[ERROR] pytesseract import error: {str(e)}")
    else:
        print(f"[ERROR] Tesseract not found at: {tesseract_path}")
    
    # Configure Poppler path for pdf2image
    POPPLER_PATH = r'C:\poppler\poppler-25.12.0\Library\bin'
    
    if os.path.exists(POPPLER_PATH):
        # Add Poppler to PATH for this session
        os.environ['PATH'] = f"{POPPLER_PATH};{os.environ['PATH']}"
        print(f"[OK] Poppler configured at: {POPPLER_PATH}")
        
        # Test pdftoppm
        pdftoppm_path = os.path.join(POPPLER_PATH, 'pdftoppm.exe')
        if os.path.exists(pdftoppm_path):
            print(f"[OK] Found pdftoppm at: {pdftoppm_path}")
        else:
            print(f"[ERROR] pdftoppm not found at: {pdftoppm_path}")
    else:
        print(f"[ERROR] Poppler not found at: {POPPLER_PATH}")
        POPPLER_PATH = None
else:
    POPPLER_PATH = None


def extract_text_from_file(filename: str, content: bytes) -> tuple[str, dict]:
    """
    Extract text from file. Returns (text, metadata) where metadata contains OCR info.
    
    Args:
        filename: Name of the file being processed
        content: Raw file content as bytes
        
    Returns:
        tuple: (extracted_text, metadata_dict)
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
                    if ocr_text.strip():
                        ocr_pages.append(ocr_text)
                        print(f"Page {i}: Extracted {len(ocr_text)} characters")

                if ocr_pages:
                    text = "\n\n".join(ocr_pages)
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

        return text, ocr_info
    
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
            return text, ocr_info
        except Exception as e:
            print(f"Image OCR failed: {e}")
            return "", {"used": False, "error": str(e)}
    
    # Treat everything else as text
    try:
        text = content.decode("utf-8", errors="ignore")
        return text, ocr_info
    except Exception:
        text = content.decode(errors="ignore")
        return text, ocr_info


def split_into_clauses(text: str) -> List[str]:
    if not text:
        return []
    # Normalize line endings
    t = re.sub(r"\r\n?", "\n", text).strip()

    # Collapse single newlines within paragraphs into spaces, but keep blank lines as paragraph separators
    # First, normalize multiple blank lines
    t = re.sub(r"\n{3,}", "\n\n", t)
    # Replace single newlines that are not followed by another newline with a space
    t = re.sub(r"(?<!\n)\n(?!\n)", " ", t)

    # Split by numbered headings or paragraph breaks
    parts = re.split(r"(?:(?:^|\n)\s*\d+[\.)]\s+)|(?:\n{2,})|(?:\n(?=[A-Z][A-Za-z ]{3,}:))", t)
    parts = [p.strip() for p in parts if p and p.strip()]

    # Filter out very short fragments
    refined = [p for p in parts if len(p) >= 40]

    # Remove boilerplate headers/footers/signature blocks
    NOISE_PATTERNS = [
        r"^service agreement\b",
        r"\bagreement is made between\b",
        r"^signatures?:?\b",
        r"^signed by\b",
        r"representative:\s*_{3,}",
        r"_{5,}",
        r"^witness(ed)?\b",
    ]
    def is_noise(s: str) -> bool:
        t = (s or "").strip().lower()
        for pat in NOISE_PATTERNS:
            if re.search(pat, t, flags=re.IGNORECASE):
                return True
        return False
    refined = [c for c in refined if not is_noise(c)]

    return refined


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
