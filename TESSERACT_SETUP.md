# Tesseract OCR Setup for Windows

## Required for Image-Based PDF Analysis

The application now supports OCR (Optical Character Recognition) to extract text from image-based PDFs and image files (JPG, PNG, etc.).

### Installation Steps:

1. **Download Tesseract OCR for Windows:**
   - Go to: https://github.com/UB-Mannheim/tesseract/wiki
   - Download the latest installer (e.g., `tesseract-ocr-w64-setup-5.3.3.20231005.exe`)

2. **Install Tesseract:**
   - Run the installer
   - **Important:** Note the installation path (default: `C:\Program Files\Tesseract-OCR\`)
   - Make sure to install the English language data pack (included by default)

3. **Add Tesseract to System PATH:**
   - Right-click "This PC" → Properties → Advanced system settings
   - Click "Environment Variables"
   - Under "System variables", find "Path" and click "Edit"
   - Add new entry: `C:\Program Files\Tesseract-OCR`
   - Click OK to save

4. **Alternative: Set Path in Code (if step 3 doesn't work):**
   - Add this line to `backend/app/parser.py` at the top:
   ```python
   pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
   ```

5. **Verify Installation:**
   - Open new Command Prompt
   - Run: `tesseract --version`
   - Should show Tesseract version info

### What This Enables:

✅ **Image-based PDFs** - Scanned contracts will have text extracted automatically
✅ **Image Files** - Can upload JPG, PNG contract images directly  
✅ **Automatic Fallback** - Regular PDFs work as before, OCR only triggers when needed
✅ **Multi-page Support** - Handles multi-page scanned documents

### Supported Formats:
- PDF (text-based)
- PDF (image-based/scanned) - **NEW**
- JPG/JPEG images - **NEW**
- PNG images - **NEW**  
- BMP images - **NEW**
- TIFF images - **NEW**

### Note:
If Tesseract is not installed, the application will still work for regular text-based PDFs. OCR will simply be skipped with a warning message in the logs.
