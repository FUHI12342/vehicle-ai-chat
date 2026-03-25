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
    "禁止",
    "厳禁",
    "絶対に",
    "死亡",
    "重傷",
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
    "不具合",
    "作動しない",
    "効かない",
    "漏れ",
    "オーバーヒート",
    "診断",
    "修理",
]

PROCEDURE_KEYWORDS = [
    "手順",
    "方法",
    "操作",
    "交換",
    "取り付け",
    "取り外し",
    "調整",
    "補充",
    "充填",
    "確認方法",
    "の仕方",
]

SPEC_KEYWORDS = [
    "仕様",
    "諸元",
    "スペック",
    "容量",
    "規格",
    "定格",
    "寸法",
    "重量",
    "推奨",
    "適合",
    "型式",
]

_RX_EXCLUDE_WARNING_LAMP = re.compile(r"(警告\s*灯|表示\s*灯)")

# Diagnostic branch condition patterns (e.g. "スターターが回らない！", "正常に回るが…")
_RX_DIAGNOSTIC_CONDITION = re.compile(r"(?:[！!]|…|\.{3,})\s*$")
_RX_PAGE_REF = re.compile(r"(?:^|\s)(?:P\.|Ｐ\.)\s*\d+", re.IGNORECASE)
_RX_DOTS_PAGE = re.compile(r"[\.．]{2,}\s*\d+\s*$")  # "...... 19" みたいな行
_RX_QUICKGUIDE = re.compile(r"ク\s*イ\s*ッ\s*ク\s*ガ\s*イ\s*ド")
_RX_VISUAL_TOC = re.compile(r"ビ\s*ジ\s*ュ\s*ア\s*ル\s*目\s*次")
_RX_TOC = re.compile(r"目\s*次")


def _strip_lamp_titles_for_warning(text: str) -> str:
    return _RX_EXCLUDE_WARNING_LAMP.sub("", text or "")


def _detect_content_type(text: str) -> str:
    t = text or ""

    # Warning は最優先（安全担保）— 1つでもマッチすれば即 warning
    safe_text = _strip_lamp_titles_for_warning(t)
    safe_lower = safe_text.lower()
    for kw in WARNING_KEYWORDS:
        if kw.lower() in safe_lower:
            return "warning"

    # 残り3タイプはスコアリング方式: キーワードマッチ数で判定
    scores: dict[str, int] = {
        "troubleshooting": 0,
        "procedure": 0,
        "specification": 0,
    }
    for kw in TROUBLESHOOTING_KEYWORDS:
        if kw in t:
            scores["troubleshooting"] += 1
    for kw in PROCEDURE_KEYWORDS:
        if kw in t:
            scores["procedure"] += 1
    for kw in SPEC_KEYWORDS:
        if kw in t:
            scores["specification"] += 1

    max_score = max(scores.values())
    if max_score == 0:
        return "general"

    # 最大スコアのタイプを採用（同点時は具体的なタイプ優先: specification > procedure > troubleshooting）
    for content_type in ("specification", "procedure", "troubleshooting"):
        if scores[content_type] == max_score:
            return content_type

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

    def _split_at_branch_boundary(self, text: str) -> list[str]:
        """Split oversized text at diagnostic branch boundaries.

        Detects condition lines ending with ！ or … (common in automotive
        diagnostic flowcharts) and splits at the boundary closest to the
        text midpoint, ensuring both parts are substantial (>= 150 chars).
        """
        lines = text.split("\n")
        if len(lines) < 6:
            return [text]

        mid_char = len(text) // 2
        candidates: list[tuple[int, int]] = []
        char_pos = 0

        for i, line in enumerate(lines):
            stripped = line.strip()
            if (i >= 3
                    and stripped
                    and len(stripped) >= 5
                    and _RX_DIAGNOSTIC_CONDITION.search(stripped)):
                before_len = char_pos
                after_len = len(text) - char_pos
                if before_len >= 150 and after_len >= 150:
                    candidates.append((i, abs(char_pos - mid_char)))
            char_pos += len(line) + 1  # +1 for \n

        if not candidates:
            return [text]

        # Pick the candidate closest to the middle
        candidates.sort(key=lambda x: x[1])
        split_idx = candidates[0][0]

        part1 = "\n".join(lines[:split_idx])
        # Add 2 lines of overlap for context continuity
        overlap_start = max(0, split_idx - 2)
        overlap_lines = lines[overlap_start:split_idx]
        part2 = "\n".join(overlap_lines + lines[split_idx:])

        return [part1, part2]

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

            # Split oversized paragraphs at diagnostic branch boundaries
            if len(para) > self.target_size and "\n" in para:
                # Flush current accumulator first
                if current_text.strip():
                    chunks.append(self._make_chunk(current_text, page_number, current_section))
                    current_text = ""

                sub_paras = self._split_at_branch_boundary(para)
                for sub in sub_paras:
                    sub = sub.strip()
                    if sub:
                        section = _detect_section(sub)
                        if section:
                            current_section = section
                        chunks.append(self._make_chunk(sub, page_number, current_section))
                continue

            section = _detect_section(para)
            if section:
                current_section = section

            if _has_warning(para) and current_text:
                chunks.append(self._make_chunk(current_text, page_number, current_section))
                current_text = ""

            if len(current_text) + len(para) > self.max_size and current_text:
                chunks.append(self._make_chunk(current_text, page_number, current_section))
                overlap_text = self._sentence_aware_overlap(current_text)
                current_text = overlap_text

            current_text += ("\n\n" if current_text else "") + para

            if _has_warning(para):
                chunks.append(self._make_chunk(current_text, page_number, current_section))
                current_text = ""

        if current_text.strip():
            chunks.append(self._make_chunk(current_text, page_number, current_section))

        return chunks

    def _sentence_aware_overlap(self, text: str) -> str:
        """文境界でoverlapテキストを切り出す。

        末尾から self.overlap 文字分を取り、その中で最も先頭に近い
        文境界（。！？\n）の直後から開始する。文境界が見つからない場合は
        段落境界（\n\n）で切る。
        """
        if len(text) <= self.overlap:
            return ""
        tail = text[-self.overlap:]
        # 文境界を探す（末尾からoverlap文字内で最も古い文境界）
        for sep in ("。\n", "。", "！", "？", "\n\n", "\n"):
            pos = tail.find(sep)
            if pos >= 0 and pos < len(tail) - len(sep):
                return tail[pos + len(sep):].strip()
        # 文境界が見つからない → 空（切断テキストを引き継がない）
        return ""

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