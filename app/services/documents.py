from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

import fitz


@dataclass
class ParsedDocument:
    pages: list[str]
    toc: list[tuple[int, str, int]]
    message: str = ""
    needs_ocr: bool = False

    @property
    def text(self) -> str:
        return "\n\n".join(f"[第{i + 1}页]\n{text}" for i, text in enumerate(self.pages))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_document(path: Path) -> ParsedDocument:
    suffix = path.suffix.lower()
    if suffix in {".txt", ".md"}:
        text = path.read_text("utf-8", errors="ignore")
        return ParsedDocument([text], infer_toc([text]), "文本文件解析完成")
    if suffix != ".pdf":
        raise ValueError("当前支持 PDF、TXT 和 Markdown 文件")
    doc = fitz.open(path)
    pages = [page.get_text("text", sort=True).strip() for page in doc]
    raw_toc = doc.get_toc(simple=True)
    toc = [(int(level), str(title).strip(), int(page)) for level, title, page in raw_toc if title.strip()]
    nonempty = sum(bool(p.strip()) for p in pages)
    message = f"解析 {len(pages)} 页，其中 {nonempty} 页含可提取文本"
    needs_ocr = bool(pages and nonempty / len(pages) < 0.25)
    # Some older Chinese PDFs expose Latin letters/numbers but omit every
    # Chinese glyph from the text layer.  A plain non-empty-page check misses
    # that failure mode and sends meaningless fragments to the model.
    front_han = sum("\u4e00" <= c <= "\u9fff" for p in pages[:5] for c in p)
    body_han_pages = sum(sum("\u4e00" <= c <= "\u9fff" for c in p) >= 5 for p in pages[5:])
    if len(pages) >= 20 and front_han >= 10 and body_han_pages < max(3, int(len(pages) * 0.05)):
        needs_ocr = True
        message += "；检测到中文正文文本层缺失（仅数字/英文可提取）"
    if needs_ocr:
        message += "；该文件疑似扫描版，请安装 OCR 扩展或换用文字版 PDF"
    if not toc:
        toc = infer_toc(pages)
        message += "；未发现 PDF 书签，已从正文推断目录"
    doc.close()
    return ParsedDocument(pages, toc, message, needs_ocr)


HEADING_RE = re.compile(
    r"^\s*((第[一二三四五六七八九十百0-9]+[章节篇])|([0-9]{1,2}(?:\s*\.\s*[0-9]{1,2}){0,2}))"
    r"\s*[、．：:]?\s+(.{1,60})$"
)
NOISE_RE = re.compile(
    r"(?:https?\s*[:/,]|www\.|@|ISBN|邮政编码|出版社|出版日期|联系电话|"
    r"(?:\d{3,4}[-—]\d{6,8})|(?:\d[\d\s-]{7,}\d))",
    re.I,
)


def infer_toc(pages: list[str]) -> list[tuple[int, str, int]]:
    found: list[tuple[int, str, int]] = []
    seen: set[str] = set()
    for page_no, text in enumerate(pages, 1):
        # TXT/Markdown and pasted outlines arrive as one logical page, so scan
        # the whole document. For full PDFs keep the conservative front-of-page
        # window to avoid treating ordinary body numbering as a table of contents.
        lines = text.splitlines() if len(pages) == 1 else text.splitlines()[:35]
        for line in lines:
            line = " ".join(line.strip().strip("*").split())
            if NOISE_RE.search(line) or line.count("…") >= 2 or line.count(".") >= 8:
                continue
            m = HEADING_RE.match(line)
            if not m or len(line) > 75 or line in seen:
                continue
            numeric = re.sub(r"\s", "", m.group(3) or "")
            title = re.sub(r"(?:\s*[.．·…]{2,}\s*|\s+)\d+\s*$", "", (m.group(4) or "").strip())
            if numeric and "." not in numeric and (numeric.startswith("0") or int(numeric) > 30):
                continue
            if not re.search(r"[\u4e00-\u9fffA-Za-z]", title):
                continue
            # Preserve the chapter/section number but remove the printed page
            # column, otherwise headings become "第1章 绪论 1" in the UI.
            prefix = line[:m.start(4)]
            clean_line = (prefix + title).strip()
            seen.add(line)
            level = 1
            if numeric.count(".") >= 2:
                level = 3
            elif numeric.count(".") == 1 or "节" in line[:10]:
                level = 2
            found.append((level, clean_line, page_no))
    if not found:
        found = [(1, "全文", 1)]
    return found[:250]


def page_chunks(pages: list[str], start_page: int, end_page: int, max_chars: int = 7000):
    chunks: list[tuple[int, int, str]] = []
    buffer, begin = [], start_page
    size = 0
    for page_no in range(max(1, start_page), min(len(pages), end_page) + 1):
        text = pages[page_no - 1]
        if buffer and size + len(text) > max_chars:
            chunks.append((begin, page_no - 1, "\n".join(buffer)))
            buffer, begin, size = [], page_no, 0
        buffer.append(f"[第{page_no}页]\n{text}")
        size += len(text)
    if buffer:
        chunks.append((begin, min(len(pages), end_page), "\n".join(buffer)))
    return chunks
