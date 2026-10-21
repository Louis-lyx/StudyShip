from __future__ import annotations

import re
from collections import Counter

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..db import (
    CourseRequirement, DiagnosticAnswerKey, DiagnosticQuestion, KnowledgePoint,
    QuestionSourceItem, SourceJudgment, Topic,
)
from .external_questions import seed_external_questions

SOURCE_NAMES = {"opendsa": "OpenDSA", "yanweimin": "严蔚敏配套习题"}

GROUP_TERMS = {
    "AlgAnal": ("算法", "复杂度"), "Background": ("数据结构", "基本概念", "集合"),
    "Binary": ("树", "二叉树"), "Graph": ("图",), "Hashing": ("哈希", "散列"),
    "Indexing": ("索引", "文件"), "List": ("线性表", "链表", "栈", "队列"),
    "Pointers": ("指针", "链表", "动态存储"), "RecurTutor": ("递归",),
    "Searching": ("查找",), "Sorting": ("排序",),
}

TOKEN_TERMS = {
    "complex": ("复杂度", "算法分析"), "theta": ("复杂度",), "big-o": ("复杂度",),
    "array": ("数组", "顺序表"), "linked": ("链表",), "list": ("线性表", "链表"),
    "stack": ("栈",), "queue": ("队列",), "recurs": ("递归",),
    "binary tree": ("二叉树",), "bst": ("二叉排序树", "二叉搜索树"),
    "travers": ("遍历",), "huffman": ("赫夫曼", "哈夫曼"), "heap": ("堆",),
    "graph": ("图",), "depth": ("深度优先",), "breadth": ("广度优先",),
    "dfs": ("深度优先",), "bfs": ("广度优先",), "dijkstra": ("最短路径",),
    "floyd": ("最短路径",), "minimum spanning": ("最小生成树",),
    "topological": ("拓扑排序",), "critical path": ("关键路径",),
    "hash": ("哈希", "散列"), "collision": ("冲突", "哈希"),
    "search": ("查找",), "index": ("索引",),
    "insertion sort": ("插入排序",), "shellsort": ("希尔排序",),
    "quicksort": ("快速排序",), "selection sort": ("选择排序",),
    "heapsort": ("堆排序",), "mergesort": ("归并排序",), "radix": ("基数排序",),
    "bubble": ("冒泡排序",), "sort": ("排序",), "pointer": ("指针", "链表"),
    "string": ("串",), "matrix": ("矩阵",),
    "线性表": ("线性表",), "链表": ("链表",), "顺序表": ("顺序表",),
    "栈": ("栈",), "队列": ("队列",), "递归": ("递归",), "串": ("串",),
    "数组": ("数组",), "矩阵": ("矩阵",), "广义表": ("广义表",),
    "二叉树": ("二叉树",), "树": ("树",), "赫夫曼": ("赫夫曼", "哈夫曼"),
    "图": ("图",), "深度优先": ("深度优先",), "广度优先": ("广度优先",),
    "最小生成树": ("最小生成树",), "最短路径": ("最短路径",),
    "拓扑排序": ("拓扑排序",), "关键路径": ("关键路径",), "查找": ("查找",),
    "哈希": ("哈希", "散列"), "散列": ("散列", "哈希"), "排序": ("排序",),
    "插入排序": ("插入排序",), "快速排序": ("快速排序",), "选择排序": ("选择排序",),
    "堆排序": ("堆排序",), "归并排序": ("归并排序",), "基数排序": ("基数排序",),
    "动态存储": ("动态存储",), "文件": ("文件",),
}

YAN_CHAPTER_TERMS = {
    "01": ("绪论", "算法", "基本概念"), "02": ("线性表",),
    "03": ("栈", "队列"), "04": ("串",), "05": ("数组", "矩阵", "广义表"),
    "06": ("树", "二叉树"), "07": ("图",), "08": ("动态存储",),
}

OPENDSA_CHAPTERS = {
    "AlgAnal": (1,), "Background": (1,), "List": (2,), "Pointers": (2, 8),
    "RecurTutor": (3,), "Binary": (6,), "Graph": (7,),
    "Hashing": (9,), "Searching": (9,), "Sorting": (10,), "Indexing": (12,),
}


def _focus(req: CourseRequirement | None, difficulty: int) -> float:
    if not req:
        return min(1.0, 0.42 + 0.04 * difficulty)
    return min(1.0, max(0.05,
        0.42 * req.exam_weight + 0.18 * req.ppt_emphasis
        + 0.14 * req.assignment_weight + 0.10 * req.exam_frequency
        + 0.10 * (req.required_level / 5) + 0.06 * (difficulty / 5)
    ))


def _chapter(topic: Topic | None, topics: dict[int, Topic]) -> tuple[int | None, str]:
    if not topic:
        return None, "课程核心知识"
    current = topic
    seen: set[int] = set()
    while current.parent_id and current.parent_id in topics and current.id not in seen:
        seen.add(current.id)
        current = topics[current.parent_id]
    return current.id, current.title


def _zh_bigrams(value: str) -> set[str]:
    chars = re.findall(r"[\u4e00-\u9fff]", value)
    return {"".join(chars[i:i + 2]) for i in range(len(chars) - 1)}


def _source_terms(item: QuestionSourceItem) -> set[str]:
    text = f"{item.source_group} {item.source_ref} {item.question_text}".lower()
    terms = set(GROUP_TERMS.get(item.source_group, ()))
    if item.source_code == "yanweimin":
        terms.update(YAN_CHAPTER_TERMS.get(item.source_group[:2], ()))
    for token, mapped in TOKEN_TERMS.items():
        if token in text:
            terms.update(mapped)
    return terms


def _match_item(
    item: QuestionSourceItem,
    kps: list[KnowledgePoint],
    topics: dict[int, Topic],
    assigned: Counter,
) -> KnowledgePoint:
    terms = _source_terms(item)
    source_text = f"{item.source_ref} {item.question_text}".lower()
    question_bigrams = _zh_bigrams(item.question_text)
    best, best_score = kps[0], -1.0
    for kp in kps:
        topic = topics.get(kp.topic_id)
        _, chapter_title = _chapter(topic, topics)
        haystack = f"{kp.name} {kp.summary or ''} {topic.title if topic else ''} {chapter_title}".lower()
        score = 0.0
        if item.source_code == "yanweimin":
            number = int(item.source_group[:2]) if item.source_group[:2].isdigit() else 0
            if number and f"第{number}章" in chapter_title:
                score += 10.0
        else:
            chapter_numbers = OPENDSA_CHAPTERS.get(item.source_group, ())
            if item.source_group == "List" and any(token in source_text for token in ("stack", "queue")):
                chapter_numbers = (3,)
            elif item.source_group == "AlgAnal" and "search" in source_text:
                chapter_numbers = (9,)
            elif item.source_group == "AlgAnal" and any(
                    token in source_text for token in ("sort", "quicksort", "mergesort", "heapsort")):
                chapter_numbers = (10,)
            if any(f"第{number}章" in chapter_title for number in chapter_numbers):
                score += 8.0
        for term in terms:
            if term.lower() in haystack:
                score += 4.0 if term.lower() in kp.name.lower() else 1.8
        if item.source_code == "yanweimin":
            chapter_terms = YAN_CHAPTER_TERMS.get(item.source_group[:2], ())
            if any(term in chapter_title for term in chapter_terms):
                score += 5.0
            kp_bigrams = _zh_bigrams(haystack)
            if question_bigrams and kp_bigrams:
                score += 5.0 * len(question_bigrams & kp_bigrams) / len(question_bigrams)
        score += min(0.5, len(kp.name) / 100)
        # Generic chapter review items often carry little lexical evidence. A
        # small load penalty spreads those items across equally relevant points
        # instead of attaching an entire chapter battery to the first node.
        score -= min(2.5, 0.32 * assigned[kp.id])
        if score > best_score:
            best, best_score = kp, score
    return best


def _local_items(kps: list[KnowledgePoint], scores: dict[int, float]) -> list[dict]:
    return [{
        "kp_id": kp.id,
        "statement": (kp.summary or f"“{kp.name}”属于本课程的核心知识点。").rstrip("。") + "。",
        "explanation": kp.summary or f"该命题用于检查“{kp.name}”的基础定义。",
        "correct_answer": True,
        "source_judgment_id": None,
        "rationale": f"知识点：{kp.name}",
        "difficulty": kp.difficulty, "source": "local",
    } for kp in kps]


def rebuild_question_bank(
    db: Session,
    course_id: int,
    active_ids: set[int] | None = None,
    refresh_sources: bool = False,
) -> dict:
    source_status = seed_external_questions(db, force=refresh_sources)
    query = select(KnowledgePoint).where(
        KnowledgePoint.course_id == course_id, KnowledgePoint.approved.is_(True),
    )
    if active_ids is not None:
        query = query.where(KnowledgePoint.id.in_(active_ids or {-1}))
    kps = list(db.scalars(query.order_by(KnowledgePoint.id)).all())
    if not kps:
        return {"count": 0, "chapters": 0, "source": "empty",
                "source_counts": source_status["sources"], "message": "课程中尚无已审核知识点"}

    topics = {x.id: x for x in db.scalars(select(Topic).where(Topic.course_id == course_id)).all()}
    reqs = {x.kp_id: x for x in db.scalars(select(CourseRequirement).where(
        CourseRequirement.course_id == course_id)).all()}
    scores = {kp.id: _focus(reqs.get(kp.id), kp.difficulty) for kp in kps}
    source_items = list(db.scalars(select(QuestionSourceItem).order_by(
        QuestionSourceItem.source_code, QuestionSourceItem.id)).all())
    judgments = {x.source_item_id: x for x in db.scalars(select(SourceJudgment)).all()}

    rows: list[dict] = []
    assigned: Counter = Counter()
    for item in source_items:
        judgment = judgments.get(item.id)
        if not judgment:
            continue
        kp = _match_item(item, kps, topics, assigned)
        assigned[kp.id] += 1
        chapter_id, chapter_title = _chapter(topics.get(kp.topic_id), topics)
        rows.append({
            "kp_id": kp.id, "chapter_topic_id": chapter_id, "chapter_title": chapter_title,
            "statement": judgment.statement,
            "correct_answer": judgment.correct_answer,
            "explanation": judgment.explanation,
            "source_judgment_id": judgment.id,
            "rationale": (f"来源：{SOURCE_NAMES.get(item.source_code, item.source_code)} · "
                          f"{item.source_group} · 知识点：{judgment.concept_label or kp.name}"),
            "source": item.source_code, "focus_score": scores[kp.id], "difficulty": item.difficulty,
        })
    if not rows:
        for item in _local_items(kps, scores):
            kp = next(k for k in kps if k.id == item["kp_id"])
            chapter_id, chapter_title = _chapter(topics.get(kp.topic_id), topics)
            rows.append({**item, "chapter_topic_id": chapter_id,
                         "chapter_title": chapter_title, "focus_score": scores[kp.id]})

    old_ids = list(db.scalars(select(DiagnosticQuestion.id).where(
        DiagnosticQuestion.course_id == course_id)).all())
    if old_ids:
        db.execute(delete(DiagnosticAnswerKey).where(
            DiagnosticAnswerKey.diagnostic_question_id.in_(old_ids)))
    db.execute(delete(DiagnosticQuestion).where(DiagnosticQuestion.course_id == course_id))
    for row in rows:
        answer = {
            "correct_answer": row.pop("correct_answer"),
            "explanation": row.pop("explanation"),
            "source_judgment_id": row.pop("source_judgment_id"),
        }
        question = DiagnosticQuestion(course_id=course_id, **row)
        db.add(question)
        db.flush()
        db.add(DiagnosticAnswerKey(diagnostic_question_id=question.id, **answer))
    db.commit()
    mapped = Counter(row["source"] for row in rows)
    return {
        "count": len(rows), "chapters": len({row["chapter_title"] for row in rows}),
        "source": "external", "source_counts": dict(mapped),
        "source_pool": source_status["count"],
        "message": "OpenDSA 与严蔚敏配套习题已提炼为判断题并映射到课程知识点",
    }
