# /Users/adon/vehicle-ai-chat/backend/app/rag/chunker.py

import re
from dataclasses import dataclass, field

from app.rag.pdf_loader import PDFPage


@dataclass
class Chunk:
    text: str
    page: int
    section: str = ""
    content_type: str = "general"
    has_warning: bool = False
    metadata: dict = field(default_factory=dict)


SECTION_PATTERNS = [
    re.compile(r"^第?\s*[\d１-９]+\s*[章節]"),
    re.compile(r"^[\d１-９]+[\.\-．]\s*\S"),
    re.compile(r"^【.+】"),
    re.compile(r"^■\s*\S"),
]

WARNING_KEYWORDS = [
    "警告",
    "注意",
    "危険",
    "WARNING",
    "CAUTION",
    "DANGER",
    "やけど",
    "火災",
    "感電",
    "爆発",
]

TROUBLESHOOTING_KEYWORDS = [
    "故障",
    "トラブル",
    "症状",
    "原因",
    "対処",
    "点検",
    "異音",
    "異臭",
    "振動",
    "警告灯",
    "エラー",
]

PROCEDURE_KEYWORDS = [
    "手順",
    "方法",
    "操作",
    "交換",
    "取り付け",
    "取り外し",
]

SPEC_KEYWORDS = [
    "仕様",
    "諸元",
    "スペック",
    "容量",
    "規格",
]

_RX_EXCLUDE_WARNING_LAMP = re.compile(r"(警告\s*灯|表示\s*灯)")
_RX_PAGE_REF = re.compile(r"(?:^|\s)(?:P\.|Ｐ\.)\s*\d+", re.IGNORECASE)
_RX_DOTS_PAGE = re.compile(r"[\.．]{2,}\s*\d+\s*$")  # "...... 19" みたいな行
_RX_QUICKGUIDE = re.compile(r"ク\s*イ\s*ッ\s*ク\s*ガ\s*イ\s*ド")
_RX_VISUAL_TOC = re.compile(r"ビ\s*ジ\s*ュ\s*ア\s*ル\s*目\s*次")
_RX_TOC = re.compile(r"目\s*次")


def _strip_lamp_titles_for_warning(text: str) -> str:
    return _RX_EXCLUDE_WARNING_LAMP.sub("", text or "")


def _detect_content_type(text: str) -> str:
    t = text or ""
    lower = t.lower()

    safe_text = _strip_lamp_titles_for_warning(t)
    safe_lower = safe_text.lower()

    for kw in WARNING_KEYWORDS:
        if kw.lower() in safe_lower:
            return "warning"

    for kw in TROUBLESHOOTING_KEYWORDS:
        if kw in t:
            return "troubleshooting"

    for kw in PROCEDURE_KEYWORDS:
        if kw in t:
            return "procedure"

    for kw in SPEC_KEYWORDS:
        if kw in t:
            return "specification"

    return "general"


def _has_warning(text: str) -> bool:
    t = _strip_lamp_titles_for_warning(text or "")
    lower = t.lower()
    return any(kw.lower() in lower for kw in WARNING_KEYWORDS)


def _detect_section(text: str) -> str:
    for line in (text or "").split("\n")[:3]:
        stripped = line.strip()
        for pattern in SECTION_PATTERNS:
            if pattern.match(stripped):
                return stripped[:80]
    return ""


def _is_quickguide_or_toc_page(text: str) -> bool:
    """
    A: 除外（最速で問診ノイズ減）
    - クイックガイド（P.6〜16に相当するようなページ）を確実に拾う
    - 目次ページも拾う
    - 誤爆（本文中で「クイックガイド」と一度だけ言及、など）を避ける
    """
    if not text:
        return False

    # 1) タイトル系の強いシグナル（改行/空白がバラけても拾う）
    head = text[:800]  # 先頭付近にあるはず
    if _RX_QUICKGUIDE.search(head) or _RX_VISUAL_TOC.search(head):
        return True

    # 2) 「目次」は誤爆し得るので "先頭付近" + "目次っぽい構造" を条件にする
    if _RX_TOC.search(head):
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        if len(lines) < 10:
            return True
        p_refs = len(_RX_PAGE_REF.findall(text))
        dot_pages = sum(1 for ln in lines if _RX_DOTS_PAGE.search(ln))
        short_lines = sum(1 for ln in lines if len(ln) <= 12)
        avg_len = sum(len(ln) for ln in lines) / max(1, len(lines))

        if (p_refs >= 6) or (dot_pages >= 6):
            return True
        if short_lines / max(1, len(lines)) >= 0.55 and avg_len <= 22:
            return True

    # 3) クイックガイド “っぽさ” ヒューリスティック（タイトルが落ちてるPDFにも対応）
    #    - P.xx が大量
    #    - 短い行が多い
    #    - 平均行長が短い
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if len(lines) >= 12:
        p_refs = len(_RX_PAGE_REF.findall(text))
        short_lines = sum(1 for ln in lines if len(ln) <= 10)
        avg_len = sum(len(ln) for ln in lines) / max(1, len(lines))

        # ただの通常本文は平均行長が長くなりがちなので、ここは厳しめに
        if p_refs >= 10 and short_lines / max(1, len(lines)) >= 0.55 and avg_len <= 18:
            return True

    return False


class AutomotiveChunker:
    def __init__(
        self,
        target_size: int = 600,
        overlap: int = 100,
        max_size: int = 1000,
        exclude_quickguide: bool = True,
    ):
        self.target_size = target_size
        self.overlap = overlap
        self.max_size = max_size
        self.exclude_quickguide = exclude_quickguide

    def chunk_pages(self, pages: list[PDFPage]) -> list[Chunk]:
        chunks: list[Chunk] = []
        for page in pages:
            full_text = page.text or ""

            if self.exclude_quickguide and _is_quickguide_or_toc_page(full_text):
                continue

            for table in getattr(page, "tables", []) or []:
                table_text = "\n".join([" | ".join(row) for row in table])
                full_text += "\n\n" + table_text

            page_chunks = self._split_text(full_text, page.page_number)
            chunks.extend(page_chunks)

        return chunks

    def _split_text(self, text: str, page_number: int) -> list[Chunk]:
        if not (text or "").strip():
            return []

        paragraphs = re.split(r"\n{2,}", text)
        chunks: list[Chunk] = []
        current_text = ""
        current_section = ""

        for para in paragraphs:
            para = (para or "").strip()
            if not para:
                continue

            section = _detect_section(para)
            if section:
                current_section = section

            if _has_warning(para) and current_text:
                chunks.append(self._make_chunk(current_text, page_number, current_section))
                current_text = ""

            if len(current_text) + len(para) > self.max_size and current_text:
                chunks.append(self._make_chunk(current_text, page_number, current_section))
                overlap_text = current_text[-self.overlap:] if len(current_text) > self.overlap else ""
                current_text = overlap_text

            current_text += ("\n\n" if current_text else "") + para

            if _has_warning(para):
                chunks.append(self._make_chunk(current_text, page_number, current_section))
                current_text = ""

        if current_text.strip():
            chunks.append(self._make_chunk(current_text, page_number, current_section))

        return chunks

    def _make_chunk(self, text: str, page: int, section: str) -> Chunk:
        txt = (text or "").strip()
        return Chunk(
            text=txt,
            page=page,
            section=section,
            content_type=_detect_content_type(txt),
            has_warning=_has_warning(txt),
        )


chunker = AutomotiveChunker()