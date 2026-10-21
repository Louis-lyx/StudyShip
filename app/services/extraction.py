from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Callable

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..db import (
    Book, CourseKnowledgeBinding, CourseRequirement, Enrollment, Evidence, KnowledgePoint, KnowledgeRelation,
    PlanItem, QuizAttempt, Resource, StudentState, StudyPlan, Topic,
)
from .documents import ParsedDocument, parse_document
from .llm import llm

STOPWORDS = {
    "本章", "本节", "内容", "学习", "知识", "问题", "方法", "过程", "进行", "可以", "主要",
    "以及", "其中", "一个", "一种", "相关", "基本", "一般", "通过", "对于", "根据", "掌握",
}
NONACADEMIC_RE = re.compile(
    r"(?:图书分类标识|联系电话|出版社网址|邮政编码|电子邮箱|版权页|印刷批次|"
    r"国际标准书号|ISBN|CIP|https?\s*[:/,]|www\.|@|(?:\d{3,4}[-—]\d{6,8}))",
    re.I,
)


def normalize_name(name: str) -> str:
    return re.sub(r"[\s，。；、:：()（）\-—]", "", name).lower()


def safe_int(value, default: int) -> int:
    """Coerce occasionally-null model fields to a safe integer."""
    try:
        if value is None or (isinstance(value, str) and not value.strip()):
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def safe_float(value, default: float) -> float:
    """Coerce occasionally-null model fields to a safe float."""
    try:
        if value is None or (isinstance(value, str) and not value.strip()):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _fallback_points(title: str, text: str, start: int, end: int) -> list[dict]:
    candidates: list[str] = []
    for line in text.splitlines():
        clean = re.sub(r"\[第\d+页\]", "", line).strip()
        if 3 <= len(clean) <= 36 and (
            re.match(r"^(?:\d+(?:\.\d+)*|第.{1,8}[节章])", clean)
            or clean.endswith(("算法", "结构", "原理", "方法", "模型", "定理", "概念", "定义"))
        ):
            clean = re.sub(r"^(?:\d+(?:\.\d+)*|第.{1,8}[节章])\s*[、.．：:]?\s*", "", clean)
            if clean and clean not in candidates:
                candidates.append(clean)
    if title and title not in {"全文"}:
        candidates.insert(0, re.sub(r"^(?:\d+(?:\.\d+)*)\s*", "", title).strip())
    if not candidates:
        words = re.findall(r"[\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z0-9\-]{2,14}", text)
        candidates = [w for w, _ in Counter(w for w in words if w not in STOPWORDS).most_common(5)]
    output = []
    for name in candidates[:8]:
        if len(name) > 40 or len(name) < 2:
            continue
        pos = text.find(name)
        evidence = text[max(0, pos - 50): pos + 180].replace("\n", " ") if pos >= 0 else text[:180]
        if NONACADEMIC_RE.search(name + " " + evidence):
            continue
        output.append({
            "name": name, "summary": evidence[:200], "difficulty": 2,
            "estimated_minutes": 45, "start_page": start, "end_page": end,
            "evidence": evidence[:240], "confidence": 0.55,
        })
    return output


def build_book_knowledge(db: Session, book: Book, parsed: ParsedDocument,
                         progress_callback: Callable[..., object] | None = None) -> dict:
    # Rebuilding a course is deliberately transactional and preserves a student's
    # mastery whenever a normalized knowledge-point name still exists in the new
    # edition.  Derived plans, attempts and resource links are rebuilt because
    # their foreign keys refer to the previous graph.
    old_kps = db.scalars(select(KnowledgePoint).where(
        KnowledgePoint.course_id == book.course_id
    )).all()
    for previous in db.scalars(select(Book).where(
        Book.course_id == book.course_id, Book.id != book.id, Book.status != "failed"
    )).all():
        previous.status = "superseded"
    old_ids = [kp.id for kp in old_kps]
    old_names = {kp.id: kp.normalized_name for kp in old_kps}
    state_snapshot: dict[tuple[int, str], dict] = {}
    if old_ids:
        for state in db.scalars(select(StudentState).where(StudentState.kp_id.in_(old_ids))).all():
            state_snapshot[(state.student_id, old_names[state.kp_id])] = {
                "mastery": state.mastery, "stability": state.stability,
                "review_count": state.review_count, "last_reviewed_at": state.last_reviewed_at,
                "quiz_correct": state.quiz_correct, "quiz_total": state.quiz_total,
            }
        plans = db.scalars(select(StudyPlan).where(StudyPlan.course_id == book.course_id)).all()
        plan_ids = [plan.id for plan in plans]
        if plan_ids:
            db.execute(delete(PlanItem).where(PlanItem.plan_id.in_(plan_ids)))
            db.execute(delete(StudyPlan).where(StudyPlan.id.in_(plan_ids)))
        from ..db import DiagnosticAnswerKey, DiagnosticQuestion
        diagnostic_ids = list(db.scalars(select(DiagnosticQuestion.id).where(
            DiagnosticQuestion.kp_id.in_(old_ids))).all())
        if diagnostic_ids:
            db.execute(delete(DiagnosticAnswerKey).where(
                DiagnosticAnswerKey.diagnostic_question_id.in_(diagnostic_ids)))
        db.execute(delete(DiagnosticQuestion).where(DiagnosticQuestion.kp_id.in_(old_ids)))
        db.execute(delete(QuizAttempt).where(QuizAttempt.kp_id.in_(old_ids)))
        db.execute(delete(StudentState).where(StudentState.kp_id.in_(old_ids)))
    db.execute(delete(Evidence).where(Evidence.course_id == book.course_id))
    db.execute(delete(KnowledgeRelation).where(KnowledgeRelation.course_id == book.course_id))
    db.execute(delete(CourseRequirement).where(CourseRequirement.course_id == book.course_id))
    db.execute(delete(KnowledgePoint).where(KnowledgePoint.course_id == book.course_id))
    db.execute(delete(Topic).where(Topic.course_id == book.course_id))
    db.flush()

    toc = sorted(parsed.toc, key=lambda x: (x[2], x[0]))
    topics: list[Topic] = []
    stack: dict[int, Topic] = {}
    for i, (level, title, page) in enumerate(toc):
        next_page = len(parsed.pages)
        for nl, _, np in toc[i + 1:]:
            if nl <= level:
                next_page = max(page, np - 1)
                break
        parent = stack.get(level - 1)
        topic = Topic(
            course_id=book.course_id, book_id=book.id, parent_id=parent.id if parent else None,
            title=title[:240], level=min(level, 4), start_page=max(1, page),
            end_page=max(page, next_page), sort_order=i,
        )
        db.add(topic)
        db.flush()
        topics.append(topic)
        stack[level] = topic
        for k in list(stack):
            if k > level:
                del stack[k]

    created: list[KnowledgePoint] = []
    seen: dict[str, KnowledgePoint] = {}
    extraction_topics = ([t for t in topics if not any(x.parent_id == t.id for x in topics)] or topics)[:180]
    if progress_callback:
        progress_callback(stage="正在按章节提取知识点", total_sections=len(extraction_topics),
                          completed_sections=0, current_section="")
    for index, topic in enumerate(extraction_topics, 1):
        if progress_callback:
            progress_callback(stage="正在提取知识点", total_sections=len(extraction_topics),
                              completed_sections=index - 1, current_section=topic.title)
        text = "\n".join(parsed.pages[topic.start_page - 1:topic.end_page])
        if not text.strip():
            if progress_callback:
                progress_callback(stage="正在提取知识点", total_sections=len(extraction_topics),
                                  completed_sections=index, current_section=topic.title)
            continue
        fallback = {"knowledge_points": _fallback_points(topic.title, text, topic.start_page, topic.end_page)}
        prompt = (
            f"章节：{topic.title}\n页码：{topic.start_page}-{topic.end_page}\n"
            "从以下教材原文提取可独立学习和测验的知识点。返回JSON对象，字段knowledge_points；"
            "每项包含name、summary、difficulty(1-5)、estimated_minutes、start_page、end_page、evidence、confidence。"
            "只提取本课程学科内容；版权页、ISBN、出版社、电话、邮箱、网址、邮编、印刷信息、"
            "目录页码、页眉页脚不是知识点。若当前内容不属于课程正文，knowledge_points返回空数组。"
            "不得引入原文之外的事实，evidence必须来自原文。\n\n" + text[:14000]
        )
        data = llm.json_completion("你是高校教材知识工程师，只输出JSON。", prompt, fallback)
        for item in data.get("knowledge_points", [])[:12]:
            name = str(item.get("name", "")).strip()[:240]
            summary = str(item.get("summary") or "")[:2000]
            evidence = str(item.get("evidence") or "")[:2000]
            if NONACADEMIC_RE.search(name + " " + summary + " " + evidence):
                continue
            norm = normalize_name(name)
            if len(norm) < 2:
                continue
            if norm in seen:
                continue
            kp = KnowledgePoint(
                course_id=book.course_id, topic_id=topic.id, name=name, normalized_name=norm,
                summary=summary,
                difficulty=max(1, min(5, safe_int(item.get("difficulty"), 2))),
                estimated_minutes=max(10, min(360, safe_int(item.get("estimated_minutes"), 45))),
                source_page_start=max(1, safe_int(item.get("start_page"), topic.start_page)),
                source_page_end=max(1, safe_int(item.get("end_page"), topic.end_page)),
                source_evidence=evidence,
                confidence=max(0.0, min(1.0, safe_float(item.get("confidence"), 0.65))),
                approved=False,
            )
            db.add(kp)
            db.flush()
            seen[norm] = kp
            created.append(kp)
            db.add(CourseRequirement(course_id=book.course_id, kp_id=kp.id))
        if progress_callback:
            progress_callback(stage="正在提取知识点", total_sections=len(extraction_topics),
                              completed_sections=index, current_section=topic.title)

    # Establish a conservative, acyclic baseline: preceding point within the same section.
    by_topic: dict[int, list[KnowledgePoint]] = {}
    for kp in created:
        by_topic.setdefault(kp.topic_id or 0, []).append(kp)
    relations = 0
    for points in by_topic.values():
        for a, b in zip(points, points[1:]):
            db.add(KnowledgeRelation(
                course_id=book.course_id, from_kp_id=a.id, to_kp_id=b.id,
                relation_type="prerequisite", confidence=0.55, approved=False,
            ))
            relations += 1
    book.status = "needs_review"
    book.page_count = len(parsed.pages)
    book.parse_message = parsed.message
    db.commit()

    # Create states for every enrolled learner, restoring matching progress.
    enrollments = db.scalars(select(Enrollment).where(
        Enrollment.course_id == book.course_id
    )).all()
    restored = 0
    for enrollment in enrollments:
        for kp in created:
            values = state_snapshot.get((enrollment.student_id, kp.normalized_name), {})
            if values:
                restored += 1
            db.add(StudentState(student_id=enrollment.student_id, kp_id=kp.id, **values))
    db.commit()

    # Existing annual materials remain useful after a textbook edition changes.
    # Re-match them to the new graph; all resulting evidence returns to review.
    rematched = 0
    for resource in db.scalars(select(Resource).where(Resource.course_id == book.course_id)).all():
        try:
            rematched += analyze_resource(db, resource, parse_document(Path(resource.file_path)))
        except Exception as exc:
            resource.status = "failed"
            resource.parse_message = f"教材更新后重新匹配失败：{exc}"
            db.commit()
    if progress_callback:
        progress_callback(stage="正在匹配已上传教学资料", total_sections=len(extraction_topics),
                          completed_sections=len(extraction_topics), current_section="")
    return {
        "topics": len(topics), "knowledge_points": len(created), "relations": relations,
        "restored_states": restored, "rematched_evidence": rematched,
        "processed_sections": len(extraction_topics),
    }


TYPE_EFFECT = {
    "syllabus": ("exam_weight", 0.88),
    "ppt": ("ppt_emphasis", 0.68),
    "assignment": ("assignment_weight", 0.72),
    "exam": ("exam_frequency", 0.82),
    "note": ("ppt_emphasis", 0.45),
    "self_study": ("personal_relevance", 0.5),
    "book": ("personal_relevance", 0.5),
    "article": ("personal_relevance", 0.5),
    "exercise": ("personal_relevance", 0.55),
}


def _resource_chunks(pages: list[str], max_chars: int = 12000, max_pages: int = 8) -> list[list[tuple[int, str]]]:
    """Keep page references while limiting each model request."""
    chunks: list[list[tuple[int, str]]] = []
    current: list[tuple[int, str]] = []
    size = 0
    for page_no, page_text in enumerate(pages, 1):
        clean = page_text.strip()
        if not clean:
            continue
        if current and (size + len(clean) > max_chars or len(current) >= max_pages):
            chunks.append(current)
            current, size = [], 0
        current.append((page_no, clean[:max_chars]))
        size += len(clean)
    if current:
        chunks.append(current)
    return chunks


def _literal_resource_matches(chunk: list[tuple[int, str]], kps: list[KnowledgePoint]) -> list[dict]:
    """Deterministic fallback and grounding hints for the model."""
    output: list[dict] = []
    seen: set[tuple[int, int]] = set()
    for page_no, text in chunk:
        compact = normalize_name(text)
        for kp in kps:
            needle = normalize_name(kp.name)
            if len(needle) < 2 or needle not in compact or (kp.id, page_no) in seen:
                continue
            seen.add((kp.id, page_no))
            idx = text.lower().find(kp.name.lower())
            if idx < 0:
                excerpt = text[:320]
            else:
                excerpt = text[max(0, idx - 80):idx + len(kp.name) + 180]
            output.append({
                "kp_id": kp.id,
                "concept_name": kp.name,
                "concept_summary": (kp.summary or excerpt)[:320],
                "page": page_no,
                "excerpt": excerpt.replace("\n", " ")[:600],
                "confidence": 0.78,
            })
    return output[:80]


def analyze_resource(db: Session, resource: Resource, parsed: ParsedDocument) -> int:
    """Extract concepts and attach them only to nodes already in the course graph.

    This function deliberately never inserts or edits Topic, KnowledgePoint, or
    KnowledgeRelation rows.  Teacher evidence waits for review; student evidence
    is a private overlay and is ready immediately.
    """
    db.execute(delete(Evidence).where(Evidence.resource_id == resource.id))
    kp_query = select(KnowledgePoint).where(KnowledgePoint.course_id == resource.course_id)
    bindings = db.scalars(select(CourseKnowledgeBinding).where(
        CourseKnowledgeBinding.course_id == resource.course_id
    )).all()
    if bindings:
        active_ids = {item.kp_id for item in bindings if item.coverage_status not in {
            "resource_only", "excluded", "not_found",
        }}
        kp_query = kp_query.where(KnowledgePoint.id.in_(active_ids or {-1}))
    kps = db.scalars(kp_query).all()
    effect_type, base_value = TYPE_EFFECT.get(resource.resource_type, ("ppt_emphasis", 0.5))
    personal = resource.audience == "personal"
    count = 0
    kp_by_id = {kp.id: kp for kp in kps}
    candidate_text = "\n".join(
        f"{kp.id}|{kp.name}|{(kp.summary or '')[:120]}" for kp in kps
    )
    seen: set[tuple[int, str, int]] = set()
    for chunk in _resource_chunks(parsed.pages):
        fallback_rows = _literal_resource_matches(chunk, kps)
        source_text = "\n\n".join(f"[第{page_no}页]\n{text}" for page_no, text in chunk)
        fallback = {"concepts": fallback_rows}
        prompt = (
            "任务：从教学或自主学习资料中提取可学习的原子概念，并把每个概念匹配到现有课程知识点。\n"
            "硬性规则：kp_id只能从下方清单选择；只返回资料原文支持的概念；找不到对应知识点时跳过；"
            "禁止创建章节、知识点或关系。返回JSON对象concepts数组，每项包含kp_id、concept_name、"
            "concept_summary、page、excerpt、confidence(0-1)。excerpt必须来自资料原文。\n\n"
            f"现有课程知识点(id|名称|摘要)：\n{candidate_text}\n\n资料：\n{source_text}"
        )
        data = llm.json_completion(
            "你是高校课程资料知识对齐助手，只能把资料内容挂接到给定知识库节点，只输出JSON。",
            prompt,
            fallback,
        )
        rows = data.get("concepts", []) if isinstance(data, dict) else fallback_rows
        for item in rows[:80]:
            try:
                kp_id = int(item.get("kp_id"))
            except (TypeError, ValueError):
                continue
            kp = kp_by_id.get(kp_id)
            if not kp:
                continue
            page_no = max(1, min(len(parsed.pages) or 1, safe_int(item.get("page"), chunk[0][0])))
            name = str(item.get("concept_name") or kp.name).strip()[:240]
            if not name:
                name = kp.name
            identity = (kp_id, normalize_name(name), page_no)
            if identity in seen:
                continue
            seen.add(identity)
            page_text = parsed.pages[page_no - 1] if parsed.pages else ""
            excerpt = str(item.get("excerpt") or page_text[:320]).replace("\n", " ")[:600]
            summary = str(item.get("concept_summary") or kp.summary or excerpt).strip()[:2000]
            emphasis = base_value
            if any(w in excerpt for w in ("重点", "必考", "熟练掌握", "综合运用")):
                emphasis = min(1.0, emphasis + 0.16)
            db.add(Evidence(
                course_id=resource.course_id, resource_id=resource.id, kp_id=kp.id,
                page=page_no, excerpt=excerpt[:600], effect_type=effect_type,
                suggested_value=emphasis,
                confidence=max(0.0, min(1.0, safe_float(item.get("confidence"), 0.72))),
                status="approved" if personal else "pending",
                student_id=resource.uploaded_by if personal else None,
                concept_name=name, concept_summary=summary,
                match_method="ai" if llm.configured else "literal",
            ))
            count += 1
    resource.extracted_text = parsed.text[:2_000_000]
    resource.page_count = len(parsed.pages)
    resource.status = ("ready" if personal else "needs_review") if count else "no_matches"
    engine_name = "AI" if llm.configured else "本地匹配"
    noun = "个人知识点映射" if personal else "待审核知识点证据"
    resource.parse_message = f"{engine_name}解析完成，生成 {count} 条{noun}；课程框架保持不变"
    db.commit()
    return count


def apply_evidence(db: Session, evidence: Evidence, approve: bool):
    evidence.status = "approved" if approve else "rejected"
    if approve and evidence.student_id is None:
        req = db.scalar(select(CourseRequirement).where(
            CourseRequirement.course_id == evidence.course_id,
            CourseRequirement.kp_id == evidence.kp_id,
        ))
        if not req:
            req = CourseRequirement(course_id=evidence.course_id, kp_id=evidence.kp_id)
            db.add(req)
            db.flush()
        field = evidence.effect_type
        if field in {"exam_weight", "ppt_emphasis", "assignment_weight", "exam_frequency"}:
            setattr(req, field, max(getattr(req, field), evidence.suggested_value))
        if field == "required_level":
            req.required_level = max(req.required_level, int(round(evidence.suggested_value)))
    db.flush()
    pending = db.scalar(select(Evidence).where(
        Evidence.resource_id == evidence.resource_id,
        Evidence.status == "pending",
    ).exists().select())
    if not pending:
        resource = db.get(Resource, evidence.resource_id)
        if resource:
            resource.status = "ready"
    db.commit()
