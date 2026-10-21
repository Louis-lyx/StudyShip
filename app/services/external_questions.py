from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..db import QuestionSourceItem, SourceJudgment

ROOT = Path(__file__).resolve().parents[2]
OPENDSA_ROOT = ROOT / "vendor" / "OpenDSAExerciseBank" / "Exercises"
YAN_ROOT = ROOT / "vendor" / "YanweiminExerciseBank" / "习题解析"
MANIFEST = ROOT / "vendor" / "question_sources.json"
TRANSLATIONS = ROOT / "vendor" / "opendsa_question_zh.json"
JUDGMENTS = ROOT / "vendor" / "judgment_questions_zh.json"


@dataclass
class _Node:
    tag: str
    attrs: dict[str, str] = field(default_factory=dict)
    parent: "_Node | None" = None
    children: list["_Node"] = field(default_factory=list)
    pieces: list[str] = field(default_factory=list)

    @property
    def classes(self) -> set[str]:
        return set(self.attrs.get("class", "").split())


class _TreeParser(HTMLParser):
    VOID = {"br", "img", "input", "meta", "link", "hr", "source"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Node("root")
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = _Node(tag, dict(attrs), self.stack[-1])
        self.stack[-1].children.append(node)
        if tag not in self.VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID:
            self.stack.pop()

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        if self.stack[-1].tag not in {"script", "style"}:
            self.stack[-1].pieces.append(data)


def _walk(node: _Node):
    yield node
    for child in node.children:
        yield from _walk(child)


def _text(node: _Node) -> str:
    parts = list(node.pieces)
    for child in node.children:
        parts.append(_text(child))
    return re.sub(r"\s+", " ", html.unescape(" ".join(parts))).strip()


def _question_text(node: _Node) -> str:
    """Read a stem while removing legacy MCQ controls, solutions and hints."""
    if node.classes & {"solution", "choices", "hints"}:
        return ""
    parts = list(node.pieces)
    for child in node.children:
        parts.append(_question_text(child))
    return re.sub(r"\s+", " ", html.unescape(" ".join(parts))).strip()


def _descendants(node: _Node, class_name: str) -> list[_Node]:
    return [item for item in _walk(node) if class_name in item.classes]


def _closest_context(node: _Node) -> _Node:
    current = node.parent or node
    for _ in range(5):
        if (_descendants(current, "solution") or _descendants(current, "hints")):
            return current
        if current.parent is None:
            break
        current = current.parent
    return node.parent or node


def _clean(value: str, limit: int = 6000) -> str:
    value = re.sub(r"\s+", " ", value).strip(" \t\r\n-:：")
    return value[:limit]


def _familiarity(question: str, language: str) -> str:
    question = _clean(question, 900)
    if language == "zh":
        return f"我熟悉这道题涉及的概念，并能说明解题依据：{question}"
    return f"我熟悉这道题涉及的概念，并能解释其判断或解法：{question}"


def parse_opendsa() -> list[dict]:
    rows: list[dict] = []
    if not OPENDSA_ROOT.is_dir():
        return rows
    translations: dict[str, str] = {}
    if TRANSLATIONS.is_file():
        try:
            translations = json.loads(TRANSLATIONS.read_text(encoding="utf-8"))
        except Exception:
            translations = {}
    for path in sorted(OPENDSA_ROOT.rglob("*.html")):
        parser = _TreeParser()
        try:
            parser.feed(path.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            continue
        questions = [x for x in _walk(parser.root) if "question" in x.classes]
        for index, node in enumerate(questions, 1):
            question = _clean(_question_text(node))
            if len(question) < 5:
                continue
            context = _closest_context(node)
            solution_nodes = _descendants(context, "solution")
            hint_nodes = _descendants(context, "hints")
            answer = _clean(_text(solution_nodes[0])) if solution_nodes else ""
            explanation = _clean(" ".join(_text(x) for x in hint_nodes), 6000)
            relative = path.relative_to(OPENDSA_ROOT).as_posix()
            source_ref = f"{relative}#{index}"
            translated = _clean(translations.get(source_ref, ""), 900)
            rows.append({
                "source_code": "opendsa",
                "source_ref": source_ref,
                "source_group": relative.split("/", 1)[0],
                "question_text": question,
                "answer_text": answer,
                "explanation": explanation,
                "familiarity_statement": _familiarity(translated or question, "zh" if translated else "en"),
                "difficulty": 3 if any(x in path.stem.lower() for x in ("pro", "summ")) else 2,
            })
    return rows


def _strip_markdown(value: str) -> str:
    value = re.sub(r"```.*?```", " 代码片段 ", value, flags=re.S)
    value = re.sub(r"!\[[^]]*]\([^)]*\)", " 题图 ", value)
    value = re.sub(r"\[([^]]+)]\([^)]*\)", r"\1", value)
    value = re.sub(r"<u>.*?</u>", "____", value, flags=re.S | re.I)
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"[*_`>#]", " ", value)
    return _clean(value)


def parse_yanweimin() -> list[dict]:
    rows: list[dict] = []
    if not YAN_ROOT.is_dir():
        return rows
    heading_re = re.compile(r"^###\s+(.+?)\s*$", re.M)
    sub_re = re.compile(r"(?m)^\s*>?\s*[（(](\d+)[）)]\s*")
    for path in sorted(YAN_ROOT.rglob("*.md")):
        raw = path.read_text(encoding="utf-8", errors="ignore")
        matches = list(heading_re.finditer(raw))
        group = path.parent.name
        for h_index, match in enumerate(matches, 1):
            heading = _strip_markdown(match.group(1))
            body = raw[match.end():matches[h_index].start() if h_index < len(matches) else len(raw)]
            sub_matches = list(sub_re.finditer(body))
            generic = any(word in heading for word in ("填空题", "选择题", "判断题"))
            if generic and sub_matches:
                for s_index, sub in enumerate(sub_matches, 1):
                    end = sub_matches[s_index].start() if s_index < len(sub_matches) else len(body)
                    question = _strip_markdown(body[sub.end():end])
                    if len(question) < 5:
                        continue
                    rows.append({
                        "source_code": "yanweimin",
                        "source_ref": f"{path.relative_to(YAN_ROOT).as_posix()}#h{h_index}s{s_index}",
                        "source_group": group,
                        "question_text": question,
                        "answer_text": "",
                        "explanation": "",
                        "familiarity_statement": _familiarity(question, "zh"),
                        "difficulty": 2,
                    })
            else:
                question = re.sub(r"^\d+(?:\.\d+)+\s*", "", heading).strip()
                if len(question) < 5:
                    continue
                rows.append({
                    "source_code": "yanweimin",
                    "source_ref": f"{path.relative_to(YAN_ROOT).as_posix()}#h{h_index}",
                    "source_group": group,
                    "question_text": question,
                    "answer_text": "",
                    "explanation": _strip_markdown(body)[:6000],
                    "familiarity_statement": _familiarity(question, "zh"),
                    "difficulty": 3 if any(x in question for x in ("证明", "算法", "编写", "设计")) else 2,
                })
    return rows


def source_manifest_version() -> str:
    if not MANIFEST.is_file():
        return ""
    try:
        data = json.loads(MANIFEST.read_text(encoding="utf-8"))
        return ":".join((data.get("opendsa", {}).get("commit", ""),
                         data.get("yanweimin", {}).get("commit", "")))
    except Exception:
        return ""


def seed_external_questions(db: Session, force: bool = False) -> dict:
    existing = db.scalar(select(func.count()).select_from(QuestionSourceItem)) or 0
    judgment_count = db.scalar(select(func.count()).select_from(SourceJudgment)) or 0
    if existing and judgment_count == existing and not force:
        counts = dict(db.execute(select(QuestionSourceItem.source_code, func.count()).group_by(
            QuestionSourceItem.source_code)).all())
        return {"count": existing, "sources": counts, "version": source_manifest_version()}

    rows = parse_opendsa() + parse_yanweimin()
    judgments = {}
    if JUDGMENTS.is_file():
        try:
            judgments = json.loads(JUDGMENTS.read_text(encoding="utf-8"))
        except Exception:
            judgments = {}
    db.execute(delete(SourceJudgment))
    db.execute(delete(QuestionSourceItem))
    for row in rows:
        source = QuestionSourceItem(**row)
        db.add(source)
        db.flush()
        key = f"{row['source_code']}:{row['source_ref']}"
        mined = judgments.get(key, {})
        statement = str(mined.get("statement", "")).strip()
        if not statement:
            statement = str(row["question_text"]).strip().rstrip("？?")
        db.add(SourceJudgment(
            source_item_id=source.id,
            statement=statement,
            correct_answer=bool(mined.get("correct", True)),
            explanation=str(mined.get("explanation", row.get("explanation", ""))).strip(),
            concept_label=str(mined.get("concept", row["source_group"])).strip()[:240],
        ))
    db.commit()
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["source_code"]] = counts.get(row["source_code"], 0) + 1
    return {"count": len(rows), "sources": counts, "version": source_manifest_version()}
