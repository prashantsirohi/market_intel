from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class ExtractedTable:
    page: int
    headers: list[str]
    rows: list[list[str]]
    raw_text: str


@dataclass
class ExtractedDocument:
    source_path: str
    total_pages: int
    full_text: str
    tables: list[ExtractedTable]
    is_scanned: bool
    extraction_method: str
    char_count: int


def needs_ocr(text: str) -> bool:
    if not text:
        return True
    
    if len(text) < 200:
        return True
    
    alpha_ratio = sum(c.isalpha() for c in text) / len(text)
    if alpha_ratio < 0.3:
        return True
    
    return False


def _needs_table_extraction(doc: dict) -> bool:
    text = " ".join(p.get("text", "") for p in doc.get("pages", []))
    return "₹" in text or "Rs." in text or "Table" in text or "," in text


class PdfExtractor:
    def __init__(self, pytesseract_available: bool = True):
        self.pytesseract_available = pytesseract_available

    def extract(self, pdf_path: str) -> ExtractedDocument:
        doc = self._extract_pymupdf(pdf_path)
        
        if _needs_table_extraction(doc):
            tables = self._extract_pdfplumber_tables(pdf_path)
            doc["tables"] = tables
        
        is_scanned = self._is_scanned(doc)
        
        if is_scanned and self.pytesseract_available:
            try:
                ocr_text = self._extract_ocr(pdf_path)
                if ocr_text:
                    doc["full_text"] = ocr_text
                    doc["extraction_method"] = "ocr"
            except Exception as e:
                logger.warning(f"OCR fallback failed: {e}")
        
        return ExtractedDocument(
            source_path=pdf_path,
            total_pages=doc.get("total_pages", 0),
            full_text=doc.get("full_text", ""),
            tables=doc.get("tables", []),
            is_scanned=is_scanned,
            extraction_method=doc.get("extraction_method", "pymupdf"),
            char_count=len(doc.get("full_text", "")),
        )

    def _extract_pymupdf(self, path: str) -> dict:
        try:
            import fitz
            doc = fitz.open(path)
            
            pages = []
            full_text_parts = []
            
            for page_num, page in enumerate(doc):
                text = page.get_text("text")
                blocks = page.get_text("blocks")
                pages.append({
                    "page": page_num + 1,
                    "text": text,
                    "blocks": blocks,
                })
                full_text_parts.append(text)
            
            return {
                "total_pages": len(doc),
                "pages": pages,
                "full_text": "\n".join(full_text_parts),
                "extraction_method": "pymupdf",
            }
        except ImportError:
            logger.warning("PyMuPDF not available, trying pdfplumber")
            return self._extract_pdfplumber_fallback(path)
        except Exception as e:
            logger.error(f"PyMuPDF extraction failed: {e}")
            return {"total_pages": 0, "pages": [], "full_text": "", "extraction_method": "error"}

    def _extract_pdfplumber_fallback(self, path: str) -> dict:
        import pdfplumber
        
        try:
            with pdfplumber.open(path) as pdf:
                pages = []
                full_text_parts = []
                
                for page_num, page in enumerate(pdf.pages):
                    text = page.extract_text() or ""
                    pages.append({
                        "page": page_num + 1,
                        "text": text,
                    })
                    full_text_parts.append(text)
                
                return {
                    "total_pages": len(pdf.pages),
                    "pages": pages,
                    "full_text": "\n".join(full_text_parts),
                    "extraction_method": "pdfplumber",
                }
        except Exception as e:
            logger.error(f"PDFplumber fallback failed: {e}")
            return {"total_pages": 0, "pages": [], "full_text": "", "extraction_method": "error"}

    def _extract_pdfplumber_tables(self, path: str) -> list[ExtractedTable]:
        tables = []
        
        try:
            import pdfplumber
            with pdfplumber.open(path) as pdf:
                for page_num, page in enumerate(pdf.pages):
                    page_tables = page.extract_tables()
                    if page_tables:
                        for table in page_tables:
                            if table and len(table) > 0:
                                headers = table[0] if table else []
                                rows = table[1:] if len(table) > 1 else []
                                raw_text = " | ".join(str(cell) for row in table for cell in row)
                                tables.append(ExtractedTable(
                                    page=page_num + 1,
                                    headers=headers,
                                    rows=rows,
                                    raw_text=raw_text,
                                ))
        except Exception as e:
            logger.warning(f"Table extraction failed: {e}")
        
        return tables

    def _extract_ocr(self, path: str) -> str:
        if not self.pytesseract_available:
            return ""
        
        try:
            import pytesseract
            from PIL import Image
            
            import fitz
            doc = fitz.open(path)
            text_parts = []
            
            for page_num in range(len(doc)):
                page = doc[page_num]
                pix = page.get_pixmap(dpi=200)
                img_data = pix.tobytes("png")
                img = Image.open(io.BytesIO(img_data))
                
                text = pytesseract.image_to_string(img)
                text_parts.append(text)
            
            return "\n".join(text_parts)
        except ImportError:
            logger.warning("pytesseract not available for OCR")
            return ""
        except Exception as e:
            logger.error(f"OCR extraction failed: {e}")
            return ""

    def _is_scanned(self, doc: dict) -> bool:
        text = doc.get("full_text", "")
        return needs_ocr(text)


import io