# /Users/adon/vehicle-ai-chat/backend/app/rag/pdf_loader.py

import io
import re
from dataclasses import dataclass

import pdfplumber

try:
    import fitz  # PyMuPDF
except Exception:  # pragma: no cover
    fitz = None


@dataclass
class PDFPage:
    page_number: int
    text: str
    tables: list[list[list[str]]]


_CID_RE = re.compile(r"\(cid:\d+\)")


def _sanitize_text(text: str) -> str:
    """Remove extraction noise and normalize whitespace."""
    if not text:
        return ""

    # Remove "(cid:xx)" noise often produced by pdfminer/pdfplumber
    text = _CID_RE.sub("", text)

    # Normalize line endings
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # Trim trailing spaces before newline
    text = re.sub(r"[ \t]+\n", "\n", text)

    # Collapse many blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def _looks_broken(text: str) -> bool:
    """Heuristic: detect 'broken' text typical of failed extraction."""
    if not text:
        return True
    if "(cid:" in text:
        return True
    if len(text) < 30:
        return True
    return False


class PDFLoader:
    """
    Extraction strategy:
      1) Try PyMuPDF (fitz) for text.
      2) If still broken, fallback to pdfplumber (layout-ish options).

    Notes:
      - Tables are NOT attached by default to avoid noisy artifacts ("|").
        If you need tables later, you can re-enable _load_tables_with_pdfplumber()
        and attach them explicitly.
    """

    def load_from_bytes(self, pdf_bytes: bytes) -> list[PDFPage]:
        # 1) Try PyMuPDF first
        pages = self._load_text_with_pymupdf(pdf_bytes)

        if pages and self._is_acceptable(pages):
            return pages

        # 2) Fallback to pdfplumber
        return self._load_with_pdfplumber(pdf_bytes)

    def load_from_path(self, path: str) -> list[PDFPage]:
        with open(path, "rb") as f:
            return self.load_from_bytes(f.read())

    # -------------------------
    # Internal implementations
    # -------------------------

    def _load_text_with_pymupdf(self, pdf_bytes: bytes) -> list[PDFPage]:
        """
        Use get_text("text") to avoid over-splitting into many blocks.
        (blocks + join with blank lines can explode paragraphs -> chunk count)
        """
        if fitz is None:
            return []

        pages: list[PDFPage] = []
        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            for i in range(doc.page_count):
                page = doc.load_page(i)

                text = page.get_text("text") or ""
                text = _sanitize_text(text)

                pages.append(PDFPage(page_number=i + 1, text=text, tables=[]))
            doc.close()
        except Exception:
            return []

        return pages

    def _load_tables_with_pdfplumber(self, pdf_bytes: bytes) -> dict[int, list[list[list[str]]]]:
        """
        Optional. Disabled by default in load_from_bytes() because tables can add noise.
        Returns: { page_number: [table1, table2, ...] }
        """
        tables_by_page: dict[int, list[list[list[str]]]] = {}
        try:
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                for i, page in enumerate(pdf.pages):
                    page_no = i + 1
                    extracted_tables = page.extract_tables() or []
                    tables: list[list[list[str]]] = []

                    for table in extracted_tables:
                        cleaned = [[cell or "" for cell in row] for row in table if row]
                        if cleaned and any(any(c.strip() for c in row) for row in cleaned):
                            tables.append(cleaned)

                    if tables:
                        tables_by_page[page_no] = tables
        except Exception:
            return {}

        return tables_by_page

    def _load_with_pdfplumber(self, pdf_bytes: bytes) -> list[PDFPage]:
        pages: list[PDFPage] = []
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for i, page in enumerate(pdf.pages):
                try:
                    text = page.extract_text(
                        layout=True,
                        x_tolerance=2,
                        y_tolerance=2,
                        use_text_flow=True,
                    ) or ""
                except TypeError:
                    text = page.extract_text() or ""

                text = _sanitize_text(text)
                pages.append(PDFPage(page_number=i + 1, text=text, tables=[]))

        return pages

    def _is_acceptable(self, pages: list[PDFPage]) -> bool:
        """Check first few pages for cid noise / extremely short text."""
        sample = pages[:3] if len(pages) >= 3 else pages
        if not sample:
            return False

        broken = sum(1 for p in sample if _looks_broken(p.text))
        # allow 0-1 broken page in the first 2-3 pages
        return broken <= max(0, len(sample) - 2)


pdf_loader = PDFLoader()