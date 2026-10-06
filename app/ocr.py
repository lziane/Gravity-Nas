import os
import pytesseract
from PIL import Image
import PyPDF2
import logging

logger = logging.getLogger("GravityNAS.OCR")

def extract_text_from_file(file_path: str) -> str:
    """Extracts text from images and PDFs for full-text search indexing."""
    if not os.path.exists(file_path):
        return ""

    ext = os.path.splitext(file_path)[1].lower()
    text = ""
    
    try:
        file_size = os.path.getsize(file_path)
        if ext in ['.png', '.jpg', '.jpeg', '.webp', '.tiff']:
            if file_size > 10 * 1024 * 1024: # 10 MB limit
                logger.warning(f"OCR skipped for {file_path}: Image size too large ({file_size} bytes)")
                return ""
            with Image.open(file_path) as img:
                # Basic OCR using Tesseract
                text = pytesseract.image_to_string(img)
        elif ext == '.pdf':
            if file_size > 30 * 1024 * 1024: # 30 MB limit
                logger.warning(f"Text extraction skipped for {file_path}: PDF size too large ({file_size} bytes)")
                return ""
            with open(file_path, "rb") as f:
                reader = PyPDF2.PdfReader(f)
                max_pages = min(len(reader.pages), 100)
                if len(reader.pages) > 100:
                    logger.warning(f"PDF text extraction truncated to 100 pages for {file_path} (total pages: {len(reader.pages)})")
                for i in range(max_pages):
                    page = reader.pages[i]
                    extracted = page.extract_text()
                    if extracted:
                        text += extracted + "\n"
    except Exception as e:
        logger.error(f"OCR failed for {file_path}: {e}")
        
    return text.strip()
