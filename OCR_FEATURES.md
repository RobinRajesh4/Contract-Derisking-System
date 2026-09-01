# OCR Features Documentation

## Overview

The Contract Derisking System now includes full OCR (Optical Character Recognition) support for processing image-based PDF contracts and direct image files. This feature automatically detects when a document is image-based and extracts text using Tesseract OCR.

## Features

### 1. Automatic OCR Detection
- When a PDF or image file is uploaded, the system checks if it contains extractable text
- If text content is less than 100 characters, OCR extraction is triggered automatically
- No user intervention required - the system handles it seamlessly

### 2. Supported File Types
- **PDF files**: Image-based or scanned PDFs
- **Image files**: JPG, JPEG, PNG, BMP, TIFF, GIF

### 3. OCR Metadata Tracking
For every document processed, the system tracks:
- `used`: Whether OCR was used (boolean)
- `method`: Extraction method ("OCR" or "Standard Text Extraction")
- `pages`: Number of pages processed
- `characters`: Total characters extracted

### 4. UI Indicators

#### Upload Page Toast Notification
When uploading a document that requires OCR:
```
Analysis complete
Analyzed 15 clauses (OCR used: 5234 characters from 3 pages)
```

#### Analyses List
Each analysis card shows an OCR indicator badge:
- Purple scan icon with "OCR Extracted" label
- Only visible for documents that were processed with OCR

#### Analysis Detail Page
Dedicated OCR information section showing:
- Extraction method badge (purple-themed)
- Pages processed count
- Characters extracted count
- Only displayed when OCR was used

## Technical Implementation

### Backend Components

#### 1. OCR Engine Setup (`backend/app/parser.py`)
```python
# Automatic path detection for Windows
tesseract_path = "C:\\Program Files\\Tesseract-OCR\\tesseract.exe"
poppler_path = "C:\\poppler\\poppler-24.08.0\\Library\\bin"
```

#### 2. Text Extraction with OCR Fallback
```python
def extract_text_from_file(filepath: str) -> Tuple[str, dict]:
    text = ""
    ocr_info = {
        "used": False,
        "method": "Standard Text Extraction",
        "pages": 0,
        "characters": 0
    }
    
    # Try standard extraction first
    # If text < 100 chars, use OCR
    # Return both text and metadata
```

#### 3. API Endpoints
All upload endpoints return OCR info:
- `POST /upload` - Single file upload
- `POST /upload/batch` - Batch upload

Response format:
```json
{
  "analysis_id": "abc123",
  "total_clauses": 15,
  "ocr_info": {
    "used": true,
    "method": "OCR",
    "pages": 3,
    "characters": 5234
  }
}
```

### Frontend Components

#### 1. Type Definitions (`src/services/analysis.ts`)
```typescript
export interface OCRInfo {
  used: boolean;
  method?: string;
  pages?: number;
  characters?: number;
}
```

#### 2. Upload Page (`src/pages/Upload.tsx`)
- Destructures `ocr_info` from upload response
- Displays OCR metadata in success toast

#### 3. Analyses List (`src/pages/Analyses.tsx`)
- Shows purple "OCR Extracted" badge for OCR-processed documents
- Badge appears in the card content section

#### 4. Analysis Detail (`src/pages/AnalysisDetail.tsx`)
- Comprehensive OCR information display
- Purple-themed badge with extraction method
- Pages and characters statistics

## OCR Quality Settings

- **DPI**: 300 (high quality)
- **Tesseract version**: 5.4.0
- **Poppler version**: 24.08.0

## Installation Requirements

### Windows
1. **Tesseract OCR**: v5.4.0+
   ```bash
   winget install UB-Mannheim.TesseractOCR
   ```

2. **Poppler**: v24.08.0+
   - Download from: https://github.com/oschwartz10612/poppler-windows/releases/
   - Extract to: `C:\poppler\`

### Python Dependencies
```txt
pytesseract==0.3.13
pdf2image==1.17.0
Pillow (already included)
```

## Performance Considerations

- OCR processing is slower than standard text extraction
- Image-based PDFs with many pages may take longer to process
- The system provides immediate feedback through UI indicators
- OCR is only triggered when necessary (text < 100 chars)

## Testing

### Test with Image-Based PDF
1. Upload a scanned contract PDF
2. Check upload toast for OCR notification
3. Navigate to analyses list - verify "OCR Extracted" badge
4. Open analysis detail - verify OCR info section

### Test with Standard PDF
1. Upload a regular text-based PDF
2. Verify no OCR indicators appear
3. Confirm faster processing time

## Future Enhancements

Potential improvements:
- Language selection for OCR
- Configurable DPI settings
- OCR confidence scores
- Pre-processing options (deskew, denoise)
- Progress indicators for large documents
- OCR result caching
