from __future__ import annotations

import secrets
import shutil
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from threading import Lock
from time import time
from typing import Literal

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from .auth import current_user, get_db, hash_password, issue_token, require_teacher, verify_password
from .db import (
    UPLOAD_DIR, Book, CanonicalKnowledgePoint, CanonicalTheoryBinding, CanonicalTopic, Course,
    CourseKnowledgeBinding, CourseOutlineBinding, CourseRequirement, CourseTemplateBinding,
    CurriculumTemplate, DiagnosticAnswerKey, DiagnosticQuestion, Enrollment, Evidence,
    KnowledgePoint, KnowledgeRelation, OutlineDocument, OutlineEntry, PlanItem, QuestionSourceItem, QuizAttempt,
    Resource, SessionLocal, StudentState, StudyPlan, TheoryModule, TheorySource, Topic, User, create_all,
)
from .services.curriculum import (
    TEMPLATE_CODE, align_outline, apply_template, build_course_from_outline, refresh_outline_coverage,
    rematch_outline,
    seed_data_structures_template,
)
from .services.documents import infer_toc, parse_document, sha256_file
from .services.extraction import analyze_resource, apply_evidence, build_book_knowledge, normalize_name
from .services.llm import llm
from .services.planner import generate_plan, ideal_total_minutes, retention, update_familiarity, update_mastery
from .services.question_bank import rebuild_question_bank
from .services.theory import SOURCE_CODE, import_opendsa_theory, theory_for_canonical_point

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"
PARSE_PROGRESS: dict[str, dict] = {}
PARSE_PROGRESS_LOCK = Lock()


class ParseCancelled(Exception):
    """Raised cooperatively between chapter-level extraction calls."""


def parse_progress_callback(job_id: str):
    def callback(**changes):
        with PARSE_PROGRESS_LOCK:
            cancelled = bool(PARSE_PROGRESS.get(job_id, {}).get("cancel_requested"))
        if cancelled:
            raise ParseCancelled("教材解析已停止")
        result = update_parse_progress(job_id, **changes)
        with PARSE_PROGRESS_LOCK:
            cancelled = bool(PARSE_PROGRESS.get(job_id, {}).get("cancel_requested"))
        if cancelled:
            raise ParseCancelled("教材解析已停止")
        return result
    return callback


def update_parse_progress(job_id: str, **changes) -> dict:
    """Keep short-lived in-memory progress available while a synchronous parse runs."""
    now = time()
    with PARSE_PROGRESS_LOCK:
        item = PARSE_PROGRESS.setdefault(job_id, {"started_at": now, "completed_sections": 0,
                                                  "total_sections": 0, "status": "queued"})
        item.update(changes)
        item["updated_at"] = now
        completed = max(0, int(item.get("completed_sections", 0) or 0))
        total = max(0, int(item.get("total_sections", 0) or 0))
        elapsed = max(0, now - item["started_at"])
        if item.get("status") == "completed":
            item["progress_percent"] = 100
            item["estimated_total_seconds"] = round(elapsed)
            item["remaining_seconds"] = 0
        elif total:
            # Before the first chapter finishes, use a conservative per-section
            # baseline.  After that, the estimate follows observed API speed.
            seconds_per_section = elapsed / completed if completed else (8.0 if llm.configured else 0.5)
            estimated_total = max(elapsed, seconds_per_section * total)
            item["progress_percent"] = min(99, max(3, int(completed * 100 / total)))
            item["estimated_total_seconds"] = round(estimated_total)
            item["remaining_seconds"] = max(0, round(estimated_total - elapsed))
        else:
            item["progress_percent"] = 3 if item.get("status") == "parsing" else 0
            item["estimated_total_seconds"] = None
            item["remaining_seconds"] = None
        item["elapsed_seconds"] = round(elapsed)
        return dict(item)


def new_parse_job_id(value: str = "") -> str:
    cleaned = "".join(ch for ch in value if ch.isalnum() or ch in "_-")[:96]
    return cleaned or secrets.token_urlsafe(18)

@asynccontextmanager
async def lifespan(_: FastAPI):
    seed_demo()
    yield


app = FastAPI(title="StudyShip", version="1.0.0", description="高校课程本地知识库与个性化学习平台",
              lifespan=lifespan)


class LoginBody(BaseModel):
    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=100)


class RegisterBody(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=8, max_length=100)
    display_name: str = Field(min_length=1, max_length=80)
    role: Literal["teacher", "student"] = "student"
    student_no: str | None = None


class CourseBody(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    code: str = Field(default="", max_length=40, pattern=r"^(?:[A-Za-z0-9_-]{2,40})?$")
    description: str = Field(default="", max_length=4000)
    academic_year: str = Field(default="2026-2027", max_length=30)


class CourseUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    code: str | None = Field(default=None, min_length=2, max_length=40,
                             pattern=r"^[A-Za-z0-9_-]+$")
    description: str | None = Field(default=None, max_length=4000)
    academic_year: str | None = Field(default=None, max_length=30)


class KPUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=240)
    summary: str | None = Field(default=None, max_length=2000)
    difficulty: int | None = Field(default=None, ge=1, le=5)
    estimated_minutes: int | None = Field(default=None, ge=10, le=720)
    approved: bool | None = None


class RelationBody(BaseModel):
    from_kp_id: int
    to_kp_id: int
    relation_type: Literal["prerequisite", "related"] = "prerequisite"
    approved: bool = True


class OutlineReviewBody(BaseModel):
    matched_topic_key: str = Field(default="", max_length=100)
    review_status: Literal["approved", "ignored", "unmatched"] = "approved"


class CoverageBody(BaseModel):
    coverage_status: Literal["course", "exam", "prerequisite", "supplemental", "excluded", "resource_only"]


class RequirementBody(BaseModel):
    included_in_exam: bool | None = None
    required_level: int | None = Field(default=None, ge=1, le=5)
    exam_weight: float | None = Field(default=None, ge=0, le=1)
    ppt_emphasis: float | None = Field(default=None, ge=0, le=1)
    assignment_weight: float | None = Field(default=None, ge=0, le=1)
    teacher_note: str | None = Field(default=None, max_length=2000)


class StateBody(BaseModel):
    mastery: float = Field(ge=0, le=1)


class PlanBody(BaseModel):
    exam_date: str
    daily_minutes: int = Field(ge=15, le=720)


class QuizSubmit(BaseModel):
    question_id: int | None = None
    kp_id: int
    question: str
    answer: str = ""
    judgment: bool | None = None
    familiar: bool | None = None
    correct: bool | None = None


def user_dict(u: User):
    return {"id": u.id, "username": u.username, "display_name": u.display_name,
            "role": u.role, "student_no": u.student_no}


def course_dict(db: Session, course: Course) -> dict:
    template_binding = db.scalar(select(CourseTemplateBinding).where(
        CourseTemplateBinding.course_id == course.id))
    template = db.get(CurriculumTemplate, template_binding.template_id) if template_binding else None
    return {
        "id": course.id, "name": course.name, "code": course.code,
        "description": course.description, "academic_year": course.academic_year,
        "published": course.published,
        "knowledge_points": db.scalar(select(func.count()).select_from(KnowledgePoint).where(
            KnowledgePoint.course_id == course.id)) or 0,
        "approved_points": db.scalar(select(func.count()).select_from(KnowledgePoint).where(
            KnowledgePoint.course_id == course.id, KnowledgePoint.approved.is_(True))) or 0,
        "students": db.scalar(select(func.count()).select_from(Enrollment).where(
            Enrollment.course_id == course.id)) or 0,
        "question_count": db.scalar(select(func.count()).select_from(DiagnosticQuestion).where(
            DiagnosticQuestion.course_id == course.id)) or 0,
        "outline_count": db.scalar(select(func.count()).select_from(OutlineDocument).where(
            OutlineDocument.course_id == course.id)) or 0,
        "template_code": template.code if template else None,
        "template_name": template.name if template else None,
    }


def assert_course_access(db: Session, course_id: int, user: User, teacher_only=False) -> Course:
    course = db.get(Course, course_id)
    if not course:
        raise HTTPException(404, "课程不存在")
    if user.role == "teacher":
        if course.owner_id != user.id:
            raise HTTPException(403, "只能管理自己创建的课程")
    else:
        if teacher_only:
            raise HTTPException(403, "此操作需要教师身份")
        enrolled = db.scalar(select(Enrollment).where(
            Enrollment.course_id == course_id, Enrollment.student_id == user.id
        ))
        if not enrolled:
            raise HTTPException(403, "尚未加入该课程")
    return course


def active_course_kp_ids(db: Session, course_id: int) -> set[int] | None:
    """Return outline-selected nodes; None means this is a legacy/free-form course."""
    bindings = db.scalars(select(CourseKnowledgeBinding).where(
        CourseKnowledgeBinding.course_id == course_id)).all()
    if not bindings:
        return None
    return {item.kp_id for item in bindings
            if item.coverage_status not in {"resource_only", "excluded", "not_found"}}


def active_topic_rows(db: Session, course_id: int) -> list[Topic]:
    outline_binding = db.scalar(select(CourseOutlineBinding).where(
        CourseOutlineBinding.course_id == course_id,
        CourseOutlineBinding.active.is_(True),
    ).order_by(CourseOutlineBinding.id.desc()))
    query = select(Topic).where(Topic.course_id == course_id)
    if outline_binding:
        query = query.where(Topic.book_id == outline_binding.book_id)
    elif db.scalar(select(CourseTemplateBinding).where(
        CourseTemplateBinding.course_id == course_id)):
        return []
    return list(db.scalars(query.order_by(Topic.sort_order)).all())


def seed_demo():
    create_all()
    db = SessionLocal()
    try:
        seed_data_structures_template(db)
        theory_root = ROOT / "vendor" / "OpenDSA"
        if (theory_root / "RST" / "en").is_dir():
            import_opendsa_theory(db, theory_root)
        # One-time migration from the former fixed course skeleton: a previously
        # uploaded outline becomes the concrete course tree; otherwise the old
        # nodes are retained only as reusable resource records.
        for template_binding in db.scalars(select(CourseTemplateBinding)).all():
            active_outline = db.scalar(select(CourseOutlineBinding).where(
                CourseOutlineBinding.course_id == template_binding.course_id,
                CourseOutlineBinding.active.is_(True),
            ))
            if active_outline:
                current_outline = db.get(OutlineDocument, active_outline.outline_id)
                current_template = db.get(CurriculumTemplate, template_binding.template_id)
                if (current_outline and current_template and
                        "细粒度资源库" not in current_outline.parse_message):
                    rematch_outline(db, current_outline, current_template)
                continue
            template = db.get(CurriculumTemplate, template_binding.template_id)
            latest_outline = db.scalar(select(OutlineDocument).where(
                OutlineDocument.course_id == template_binding.course_id,
            ).order_by(OutlineDocument.id.desc()))
            if latest_outline and template:
                build_course_from_outline(db, latest_outline, template)
            else:
                for item in db.scalars(select(CourseKnowledgeBinding).where(
                    CourseKnowledgeBinding.course_id == template_binding.course_id)).all():
                    item.coverage_status = "resource_only"
                    kp = db.get(KnowledgePoint, item.kp_id)
                    if kp:
                        kp.approved = False
                    req = db.scalar(select(CourseRequirement).where(
                        CourseRequirement.course_id == template_binding.course_id,
                        CourseRequirement.kp_id == item.kp_id))
                    if req:
                        req.included_in_exam = False
                resource_book = db.get(Book, template_binding.template_book_id)
                if resource_book:
                    resource_book.status = "resource_pool"
        db.commit()
        # A process exit terminates its parser thread. Mark those orphaned rows so
        # the teacher can clearly retry instead of seeing an endless "parsing" state.
        for interrupted in db.scalars(select(Book).where(Book.status == "parsing")).all():
            interrupted.status = "interrupted"
            interrupted.parse_message = "上次解析因程序关闭而中断，可点击重新解析"
        teacher = db.scalar(select(User).where(User.username == "demo_teacher"))
        if not teacher:
            teacher = User(username="demo_teacher", password_hash=hash_password("StudyShip@2026"),
                           display_name="演示教师", role="teacher")
            db.add(teacher); db.flush()
        student = db.scalar(select(User).where(User.username == "demo_student"))
        if not student:
            student = User(username="demo_student", password_hash=hash_password("StudyShip@2026"),
                           display_name="演示学生", role="student", student_no="20260001")
            db.add(student); db.flush()
        course = db.scalar(select(Course).where(Course.code == "DS-DEMO"))
        if not course:
            course = Course(name="数据结构（演示课程）", code="DS-DEMO",
                            description="用于在尚未上传教材时体验知识图、资料证据、学习计划和测验闭环。",
                            owner_id=teacher.id, published=True)
            db.add(course); db.flush()
            names = [
                ("算法复杂度", "分析算法时间与空间开销的方法", 2, 45),
                ("线性表", "具有线性逻辑关系的数据结构", 2, 50),
                ("栈", "后进先出的线性结构", 2, 45),
                ("队列", "先进先出的线性结构", 2, 45),
                ("树与二叉树", "层次结构及二叉树基础", 3, 80),
                ("图的存储", "邻接矩阵与邻接表", 3, 70),
                ("图的遍历", "深度优先与广度优先遍历", 3, 90),
                ("最短路径", "单源与多源最短路径算法", 4, 120),
            ]
            points = []
            for name, summary, difficulty, minutes in names:
                kp = KnowledgePoint(course_id=course.id, name=name, normalized_name=normalize_name(name),
                                    summary=summary, difficulty=difficulty, estimated_minutes=minutes,
                                    confidence=1.0, approved=True)
                db.add(kp); db.flush(); points.append(kp)
                db.add(CourseRequirement(course_id=course.id, kp_id=kp.id,
                                         exam_weight=0.55 + difficulty * 0.08, required_level=difficulty))
            for a, b in [(0,1),(1,2),(1,3),(1,4),(0,5),(5,6),(6,7)]:
                db.add(KnowledgeRelation(course_id=course.id, from_kp_id=points[a].id,
                                         to_kp_id=points[b].id, approved=True, confidence=1.0))
        if not db.scalar(select(Enrollment).where(
            Enrollment.course_id == course.id, Enrollment.student_id == student.id
        )):
            db.add(Enrollment(course_id=course.id, student_id=student.id))
        for kp in db.scalars(select(KnowledgePoint).where(KnowledgePoint.course_id == course.id)).all():
            if not db.scalar(select(StudentState).where(StudentState.student_id == student.id,
                                                        StudentState.kp_id == kp.id)):
                db.add(StudentState(student_id=student.id, kp_id=kp.id, mastery=0.25))
        db.commit()
    finally:
        db.close()


@app.get("/api/health")
def health():
    return {"ok": True, "name": "StudyShip", "version": "1.0.0", "llm_configured": llm.configured}


@app.post("/api/auth/register")
def register(body: RegisterBody, db: Session = Depends(get_db)):
    if db.scalar(select(User).where(User.username == body.username)):
        raise HTTPException(409, "用户名已存在")
    if body.role == "student" and not body.student_no:
        raise HTTPException(400, "学生需要填写学号")
    user = User(username=body.username, password_hash=hash_password(body.password),
                display_name=body.display_name, role=body.role, student_no=body.student_no)
    db.add(user); db.commit(); db.refresh(user)
    return {"token": issue_token(db, user), "user": user_dict(user)}


@app.post("/api/auth/login")
def login(body: LoginBody, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.username == body.username))
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "账号或密码错误")
    return {"token": issue_token(db, user), "user": user_dict(user)}


@app.get("/api/auth/me")
def me(user: User = Depends(current_user)):
    return user_dict(user)


@app.get("/api/courses")
def list_courses(user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.role == "teacher":
        rows = db.scalars(select(Course).where(Course.owner_id == user.id).order_by(Course.id)).all()
    else:
        rows = db.scalars(select(Course).join(Enrollment).where(Enrollment.student_id == user.id)).all()
    return [course_dict(db, c) for c in rows]


@app.get("/api/courses/available")
def available_courses(user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.role != "student": return []
    joined = select(Enrollment.course_id).where(Enrollment.student_id == user.id)
    rows = db.scalars(select(Course).where(Course.published == True, Course.id.not_in(joined))).all()  # noqa: E712
    return [{"id": c.id, "name": c.name, "code": c.code, "description": c.description} for c in rows]


@app.post("/api/courses")
def create_course(body: CourseBody, user: User = Depends(require_teacher), db: Session = Depends(get_db)):
    name = body.name.strip()
    if not name:
        raise HTTPException(422, "课程名称不能为空")
    code = body.code.strip().upper()
    if not code:
        code = f"COURSE-{secrets.token_hex(3).upper()}"
        while db.scalar(select(Course).where(Course.code == code)):
            code = f"COURSE-{secrets.token_hex(3).upper()}"
    if db.scalar(select(Course).where(Course.code == code)):
        raise HTTPException(409, "课程代码已存在")
    values = body.model_dump()
    values["name"] = name
    values["code"] = code
    c = Course(**values, owner_id=user.id)
    db.add(c); db.commit(); db.refresh(c)
    return course_dict(db, c)


@app.patch("/api/courses/{course_id}")
def update_course(course_id: int, body: CourseUpdate, user: User = Depends(require_teacher),
                  db: Session = Depends(get_db)):
    course = assert_course_access(db, course_id, user, True)
    values = body.model_dump(exclude_unset=True)
    if "name" in values:
        values["name"] = values["name"].strip()
        if not values["name"]:
            raise HTTPException(422, "课程名称不能为空")
    if "code" in values:
        values["code"] = values["code"].strip().upper()
        duplicate = db.scalar(select(Course).where(
            Course.code == values["code"], Course.id != course.id))
        if duplicate:
            raise HTTPException(409, "课程代码已存在")
    for key, value in values.items():
        setattr(course, key, value)
    db.commit(); db.refresh(course)
    return course_dict(db, course)


@app.get("/api/curriculum-templates")
def curriculum_templates(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(CurriculumTemplate).order_by(CurriculumTemplate.id)).all()
    return [{"id": row.id, "code": row.code, "name": row.name, "version": row.version,
             "description": row.description, "source_note": row.source_note} for row in rows]


@app.get("/api/theory/status")
def theory_status(user: User = Depends(current_user), db: Session = Depends(get_db)):
    source = db.scalar(select(TheorySource).where(TheorySource.code == SOURCE_CODE))
    return ({"ready": False, "modules": 0, "message": "OpenDSA 理论正文尚未导入"} if not source else
            {"ready": source.module_count > 0, "name": source.name, "version": source.version,
             "modules": source.module_count, "status": source.status, "message": source.message,
             "repository_url": source.repository_url, "imported_at": source.imported_at.isoformat()})


@app.post("/api/theory/import-opendsa")
def import_theory(user: User = Depends(require_teacher), db: Session = Depends(get_db)):
    return import_opendsa_theory(db, ROOT / "vendor" / "OpenDSA")


@app.post("/api/courses/{course_id}/curriculum-template")
def initialize_curriculum(course_id: int, template_code: str = TEMPLATE_CODE, replace_existing: bool = True,
                          user: User = Depends(require_teacher), db: Session = Depends(get_db)):
    assert_course_access(db, course_id, user, True)
    template = db.scalar(select(CurriculumTemplate).where(CurriculumTemplate.code == template_code))
    if not template:
        raise HTTPException(404, "课程基准模板不存在")
    current_binding = db.scalar(select(CourseTemplateBinding).where(
        CourseTemplateBinding.course_id == course_id, CourseTemplateBinding.template_id == template.id))
    if replace_existing and not current_binding:
        canonical_names = {normalize_name(row.name) for row in db.scalars(select(CanonicalKnowledgePoint).where(
            CanonicalKnowledgePoint.template_id == template.id)).all()}
        stale_ids = [kp.id for kp in db.scalars(select(KnowledgePoint).where(
            KnowledgePoint.course_id == course_id)).all() if kp.normalized_name not in canonical_names]
        purge_knowledge_points(db, stale_ids)
        # Relations from the former free-extraction graph are replaced by the
        # reviewed canonical prerequisite set. Matching learner states survive.
        db.execute(delete(KnowledgeRelation).where(KnowledgeRelation.course_id == course_id))
        db.commit()
    return apply_template(db, course_id, template)


@app.post("/api/courses/{course_id}/outlines")
def upload_outline(
    course_id: int, title: str = Form("本校教材目录"), outline_text: str = Form(""),
    file: UploadFile | None = File(None), user: User = Depends(require_teacher), db: Session = Depends(get_db),
):
    assert_course_access(db, course_id, user, True)
    binding = db.scalar(select(CourseTemplateBinding).where(CourseTemplateBinding.course_id == course_id))
    if not binding:
        raise HTTPException(409, "请先载入数据结构基准知识库")
    path: Path | None = None
    digest = ""
    parsed_text = outline_text.strip()
    headings: list[tuple[int, str, int]] = []
    if file and file.filename:
        path, digest = save_upload(file, course_id)
        parsed = parse_document(path)
        if parsed.needs_ocr:
            path.unlink(missing_ok=True)
            raise HTTPException(422, f"目录解析失败：{parsed.message}")
        parsed_text = parsed.text
        headings = parsed.toc
    if not headings and parsed_text:
        headings = infer_toc([parsed_text])
    headings = [x for x in headings if x[1] != "全文"]
    if not headings:
        if path:
            path.unlink(missing_ok=True)
        raise HTTPException(422, "目录中未识别到章或节；可在文本框中按“第一章 标题、1.1 标题”逐行粘贴")
    outline = OutlineDocument(course_id=course_id, title=title[:240], file_path=str(path or ""),
                              file_hash=digest, raw_text=parsed_text[:500_000])
    db.add(outline); db.flush()
    template = db.get(CurriculumTemplate, binding.template_id)
    result = align_outline(db, outline, headings, template)
    return {"id": outline.id, **result}


@app.post("/api/outlines/{outline_id}/reparse")
def reparse_outline(outline_id: int, user: User = Depends(require_teacher),
                    db: Session = Depends(get_db)):
    """Re-run a saved pasted/file outline after parser improvements."""
    previous = db.get(OutlineDocument, outline_id)
    if not previous:
        raise HTTPException(404, "目录版本不存在")
    assert_course_access(db, previous.course_id, user, True)
    if not previous.raw_text.strip():
        raise HTTPException(422, "该目录版本没有保存可重新解析的文本")
    headings = [item for item in infer_toc([previous.raw_text]) if item[1] != "全文"]
    if not headings:
        raise HTTPException(422, "目录文本中未识别到章或节")
    template_binding = db.scalar(select(CourseTemplateBinding).where(
        CourseTemplateBinding.course_id == previous.course_id))
    if not template_binding:
        raise HTTPException(409, "请先载入 OpenDSA 理论资源库")
    outline = OutlineDocument(course_id=previous.course_id,
                              title=f"{previous.title}（重新解析）"[:240],
                              file_path=previous.file_path, file_hash=previous.file_hash,
                              raw_text=previous.raw_text)
    db.add(outline); db.flush()
    result = align_outline(db, outline, headings,
                           db.get(CurriculumTemplate, template_binding.template_id))
    return {"id": outline.id, **result}


@app.get("/api/courses/{course_id}/outline-review")
def outline_review(course_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    assert_course_access(db, course_id, user)
    binding = db.scalar(select(CourseTemplateBinding).where(CourseTemplateBinding.course_id == course_id))
    if not binding:
        return {"template": None, "outlines": [], "chapters": []}
    template = db.get(CurriculumTemplate, binding.template_id)
    canonical_topics = db.scalars(select(CanonicalTopic).where(
        CanonicalTopic.template_id == template.id).order_by(CanonicalTopic.sort_order)).all()
    topic_by_key = {t.canonical_key: t for t in canonical_topics}
    local_topics = active_topic_rows(db, course_id)
    canonical_points = {p.canonical_key: p for p in db.scalars(select(CanonicalKnowledgePoint).where(
        CanonicalKnowledgePoint.template_id == template.id).order_by(
        CanonicalKnowledgePoint.sort_order)).all()}
    kp_bindings = db.scalars(select(CourseKnowledgeBinding).where(
        CourseKnowledgeBinding.course_id == course_id)).all()
    kp_rows = {k.id: k for k in db.scalars(select(KnowledgePoint).where(
        KnowledgePoint.course_id == course_id)).all()}
    theory_counts = dict(db.execute(
        select(CanonicalTheoryBinding.canonical_point_key, func.count(CanonicalTheoryBinding.id))
        .group_by(CanonicalTheoryBinding.canonical_point_key)).all())
    points_by_topic: dict[int, list[dict]] = {}
    for item in kp_bindings:
        canonical = canonical_points.get(item.canonical_key)
        kp = kp_rows.get(item.kp_id)
        if not kp or item.coverage_status in {"resource_only", "excluded", "not_found"}:
            continue
        points_by_topic.setdefault(kp.topic_id or -1, []).append({
            "id": kp.id, "canonical_key": item.canonical_key, "name": kp.name,
            "summary": kp.summary, "approved": kp.approved, "difficulty": kp.difficulty,
            "estimated_minutes": kp.estimated_minutes, "coverage_status": item.coverage_status,
            "matched_outline_title": item.matched_outline_title,
            "match_confidence": item.match_confidence,
            "theory_modules": theory_counts.get(item.canonical_key, 0),
            "source_kind": "local" if item.canonical_key.startswith("LOCAL.") else "opendsa",
        })
    chapters = []
    for chapter in [t for t in local_topics if not t.parent_id]:
        sections = []
        if points_by_topic.get(chapter.id):
            sections.append({"key": f"topic:{chapter.id}", "title": "本章知识点",
                             "topic_id": chapter.id, "points": points_by_topic[chapter.id]})
        for section in [t for t in local_topics if t.parent_id == chapter.id]:
            nested_ids = [section.id]
            frontier = [section.id]
            while frontier:
                child_ids = [t.id for t in local_topics if t.parent_id in frontier]
                nested_ids.extend(child_ids); frontier = child_ids
            section_points = [point for topic_id in nested_ids for point in points_by_topic.get(topic_id, [])]
            sections.append({"key": f"topic:{section.id}", "title": section.title,
                             "topic_id": section.id, "points": section_points})
        chapters.append({"key": f"topic:{chapter.id}", "title": chapter.title,
                         "topic_id": chapter.id, "sections": sections})
    outlines = db.scalars(select(OutlineDocument).where(
        OutlineDocument.course_id == course_id).order_by(OutlineDocument.id.desc())).all()
    outline_data = []
    for outline in outlines:
        entries = db.scalars(select(OutlineEntry).where(
            OutlineEntry.outline_id == outline.id).order_by(OutlineEntry.sort_order)).all()
        outline_data.append({"id": outline.id, "title": outline.title, "status": outline.status,
                             "message": outline.parse_message,
                             "entries": [{"id": e.id, "parent_id": e.parent_id, "title": e.title,
                                          "level": e.level, "matched_topic_key": e.matched_topic_key,
                                          "confidence": e.confidence, "review_status": e.review_status,
                                          "matched_topic_title": (
                                              canonical_points[e.matched_topic_key[3:]].name
                                              if e.matched_topic_key.startswith("KP:") and
                                              e.matched_topic_key[3:] in canonical_points else
                                              topic_by_key[e.matched_topic_key].title
                                              if e.matched_topic_key in topic_by_key else ""
                                          )} for e in entries]})
    source = db.scalar(select(TheorySource).where(TheorySource.code == SOURCE_CODE))
    return {"template": {"code": template.code, "name": template.name, "version": template.version,
                         "resource_points": len(canonical_points),
                         "theory_modules": source.module_count if source else 0},
            "canonical_topics": ([{"key": topic.canonical_key, "parent_key": topic.parent_key,
                                    "title": topic.title, "level": topic.level, "kind": "topic"}
                                   for topic in canonical_topics] +
                                  [{"key": f"KP:{point.canonical_key}", "parent_key": point.topic_key,
                                    "title": point.name, "level": 3, "kind": "point"}
                                   for point in canonical_points.values()]),
            "outlines": outline_data, "chapters": chapters}


@app.patch("/api/outline-entries/{entry_id}")
def review_outline_entry(entry_id: int, body: OutlineReviewBody,
                         user: User = Depends(require_teacher), db: Session = Depends(get_db)):
    entry = db.get(OutlineEntry, entry_id)
    if not entry:
        raise HTTPException(404, "目录项不存在")
    outline = db.get(OutlineDocument, entry.outline_id)
    assert_course_access(db, outline.course_id, user, True)
    entry.matched_topic_key = body.matched_topic_key
    entry.review_status = body.review_status
    template_binding = db.scalar(select(CourseTemplateBinding).where(
        CourseTemplateBinding.course_id == outline.course_id))
    if template_binding:
        refresh_outline_coverage(db, outline, db.get(CurriculumTemplate, template_binding.template_id))
    db.commit()
    return {"ok": True}


@app.patch("/api/knowledge/{kp_id}/coverage")
def update_coverage(kp_id: int, body: CoverageBody, user: User = Depends(require_teacher),
                    db: Session = Depends(get_db)):
    kp = db.get(KnowledgePoint, kp_id)
    if not kp:
        raise HTTPException(404, "知识点不存在")
    assert_course_access(db, kp.course_id, user, True)
    binding = db.scalar(select(CourseKnowledgeBinding).where(CourseKnowledgeBinding.kp_id == kp_id))
    if not binding:
        raise HTTPException(404, "该知识点未绑定基准框架")
    binding.coverage_status = body.coverage_status
    req = db.scalar(select(CourseRequirement).where(
        CourseRequirement.course_id == kp.course_id, CourseRequirement.kp_id == kp.id))
    if not req:
        req = CourseRequirement(course_id=kp.course_id, kp_id=kp.id)
        db.add(req)
    if body.coverage_status in {"excluded", "resource_only"}:
        req.included_in_exam = False
        kp.approved = False
    elif body.coverage_status in {"course", "exam", "prerequisite", "supplemental"}:
        req.included_in_exam = True
    db.commit()
    return {"ok": True}


@app.post("/api/topics/{topic_id}/approve")
def approve_topic(topic_id: int, user: User = Depends(require_teacher), db: Session = Depends(get_db)):
    topic = db.get(Topic, topic_id)
    if not topic:
        raise HTTPException(404, "章节不存在")
    assert_course_access(db, topic.course_id, user, True)
    child_ids = [topic.id]
    frontier = [topic.id]
    while frontier:
        children = db.scalars(select(Topic.id).where(Topic.parent_id.in_(frontier))).all()
        child_ids.extend(children); frontier = list(children)
    points = db.scalars(select(KnowledgePoint).where(KnowledgePoint.topic_id.in_(child_ids))).all()
    for kp in points:
        kp.approved = True
    point_ids = [kp.id for kp in points]
    rels = db.scalars(select(KnowledgeRelation).where(
        KnowledgeRelation.course_id == topic.course_id,
        KnowledgeRelation.from_kp_id.in_(point_ids or [-1]),
        KnowledgeRelation.to_kp_id.in_(point_ids or [-1]),
    )).all()
    for rel in rels:
        rel.approved = True
    db.commit()
    return {"knowledge_points": len(points), "relations": len(rels)}


@app.post("/api/courses/{course_id}/enroll")
def enroll(course_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.role != "student": raise HTTPException(400, "只有学生账号需要加入课程")
    course = db.get(Course, course_id)
    if not course or not course.published: raise HTTPException(404, "课程未发布")
    if not db.scalar(select(Enrollment).where(Enrollment.course_id == course_id,
                                              Enrollment.student_id == user.id)):
        db.add(Enrollment(course_id=course_id, student_id=user.id)); db.flush()
        active_ids = active_course_kp_ids(db, course_id)
        query = select(KnowledgePoint).where(KnowledgePoint.course_id == course_id,
                                             KnowledgePoint.approved == True)  # noqa: E712
        if active_ids is not None:
            query = query.where(KnowledgePoint.id.in_(active_ids or {-1}))
        for kp in db.scalars(query).all():
            db.add(StudentState(student_id=user.id, kp_id=kp.id))
        db.commit()
    return {"ok": True}


@app.post("/api/courses/{course_id}/publish")
def publish_course(course_id: int, user: User = Depends(require_teacher), db: Session = Depends(get_db)):
    course = assert_course_access(db, course_id, user, True)
    active_ids = active_course_kp_ids(db, course_id)
    query = select(func.count()).select_from(KnowledgePoint).where(
        KnowledgePoint.course_id == course_id, KnowledgePoint.approved == True)  # noqa: E712
    if active_ids is not None:
        query = query.where(KnowledgePoint.id.in_(active_ids or {-1}))
    approved = db.scalar(query)
    if not approved: raise HTTPException(400, "至少审核通过一个知识点后才能发布")
    course.published = True; db.commit()
    return {"ok": True, "approved_knowledge_points": approved}


def save_upload(upload: UploadFile, course_id: int) -> tuple[Path, str]:
    suffix = Path(upload.filename or "file.pdf").suffix.lower()
    if suffix not in {".pdf", ".txt", ".md"}: raise HTTPException(400, "支持 PDF、TXT、Markdown")
    folder = UPLOAD_DIR / str(course_id); folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{secrets.token_hex(12)}{suffix}"
    with path.open("wb") as f: shutil.copyfileobj(upload.file, f)
    return path, sha256_file(path)


def purge_knowledge_points(db: Session, kp_ids: list[int]) -> None:
    """Remove selected graph nodes and every derived row that references them."""
    if not kp_ids:
        return
    db.execute(delete(KnowledgeRelation).where(or_(
        KnowledgeRelation.from_kp_id.in_(kp_ids), KnowledgeRelation.to_kp_id.in_(kp_ids)
    )))
    db.execute(delete(Evidence).where(Evidence.kp_id.in_(kp_ids)))
    db.execute(delete(CourseRequirement).where(CourseRequirement.kp_id.in_(kp_ids)))
    db.execute(delete(PlanItem).where(PlanItem.kp_id.in_(kp_ids)))
    diagnostic_ids = list(db.scalars(select(DiagnosticQuestion.id).where(
        DiagnosticQuestion.kp_id.in_(kp_ids))).all())
    if diagnostic_ids:
        db.execute(delete(DiagnosticAnswerKey).where(
            DiagnosticAnswerKey.diagnostic_question_id.in_(diagnostic_ids)))
    db.execute(delete(DiagnosticQuestion).where(DiagnosticQuestion.kp_id.in_(kp_ids)))
    db.execute(delete(QuizAttempt).where(QuizAttempt.kp_id.in_(kp_ids)))
    db.execute(delete(StudentState).where(StudentState.kp_id.in_(kp_ids)))
    db.execute(delete(CourseKnowledgeBinding).where(CourseKnowledgeBinding.kp_id.in_(kp_ids)))
    db.execute(delete(KnowledgePoint).where(KnowledgePoint.id.in_(kp_ids)))


@app.post("/api/courses/{course_id}/books")
def upload_book(
    course_id: int, file: UploadFile = File(...), title: str = Form(...), author: str = Form(""),
    publisher: str = Form(""), edition: str = Form(""), isbn: str = Form(""),
    job_token: str = Form(""),
    user: User = Depends(require_teacher), db: Session = Depends(get_db),
):
    assert_course_access(db, course_id, user, True)
    job_id = new_parse_job_id(job_token)
    update_parse_progress(job_id, status="parsing", stage="正在保存教材文件", course_id=course_id,
                          user_id=user.id, book_id=None, completed_sections=0, total_sections=0)
    path, digest = save_upload(file, course_id)
    duplicate = db.scalar(select(Book).where(Book.course_id == course_id, Book.file_hash == digest))
    if duplicate:
        path.unlink(missing_ok=True)
        update_parse_progress(job_id, status="completed", stage="检测到重复教材", book_id=duplicate.id)
        return {"id": duplicate.id, "job_id": job_id, "duplicate": True, "status": duplicate.status}
    book = Book(course_id=course_id, title=title, author=author, publisher=publisher,
                edition=edition, isbn=isbn, file_path=str(path), file_hash=digest)
    db.add(book); db.commit(); db.refresh(book)
    book.status = "parsing"; book.parse_message = "正在解析教材并提取知识点"
    db.commit()
    update_parse_progress(job_id, status="parsing", stage="正在读取 PDF 与目录", book_id=book.id)
    try:
        parsed = parse_document(path)
        if parsed.needs_ocr:
            raise ValueError(parsed.message)
        result = build_book_knowledge(db, book, parsed, progress_callback=parse_progress_callback(job_id))
        update_parse_progress(job_id, status="completed", stage="知识库构建完成", book_id=book.id,
                              completed_sections=result.get("processed_sections", 0))
        return {"id": book.id, "job_id": job_id, "duplicate": False, **result, "message": book.parse_message}
    except ParseCancelled:
        db.rollback()
        stopped = db.get(Book, book.id)
        if stopped:
            stopped.status = "cancelled"
            stopped.parse_message = "解析已由教师停止；本轮尚未提交的知识库变更已回滚"
            db.commit()
        update_parse_progress(job_id, status="cancelled", stage="解析已停止", error="", book_id=book.id)
        raise HTTPException(409, "教材解析已停止")
    except Exception as exc:
        db.rollback()
        failed = db.get(Book, book.id)
        if failed:
            failed.status = "failed"; failed.parse_message = str(exc)[:2000]; db.commit()
        update_parse_progress(job_id, status="failed", stage="解析失败", error=str(exc)[:500], book_id=book.id)
        raise HTTPException(422, f"教材解析失败：{exc}")


@app.get("/api/courses/{course_id}/books")
def list_books(course_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    assert_course_access(db, course_id, user)
    rows = db.scalars(select(Book).where(Book.course_id == course_id).order_by(Book.id.desc())).all()
    return [{"id": b.id, "title": b.title, "author": b.author, "edition": b.edition,
             "page_count": b.page_count, "status": b.status, "message": b.parse_message} for b in rows]


@app.post("/api/books/{book_id}/retry")
def retry_book_parse(book_id: int, job_token: str = "", user: User = Depends(require_teacher),
                     db: Session = Depends(get_db)):
    book = db.get(Book, book_id)
    if not book: raise HTTPException(404, "教材不存在")
    assert_course_access(db, book.course_id, user, True)
    path = Path(book.file_path)
    if not path.is_file():
        raise HTTPException(404, "教材原文件不存在，请重新上传")
    job_id = new_parse_job_id(job_token)
    update_parse_progress(job_id, status="parsing", stage="正在重新读取 PDF 与目录", course_id=book.course_id,
                          user_id=user.id, book_id=book.id, completed_sections=0, total_sections=0)
    book.status = "parsing"; book.parse_message = "正在重新解析教材并提取知识点"
    db.commit()
    try:
        parsed = parse_document(path)
        if parsed.needs_ocr:
            raise ValueError(parsed.message)
        result = build_book_knowledge(db, book, parsed, progress_callback=parse_progress_callback(job_id))
        update_parse_progress(job_id, status="completed", stage="知识库构建完成", book_id=book.id,
                              completed_sections=result.get("processed_sections", 0))
        return {"id": book.id, "job_id": job_id, **result, "message": book.parse_message}
    except ParseCancelled:
        db.rollback()
        stopped = db.get(Book, book_id)
        if stopped:
            stopped.status = "cancelled"
            stopped.parse_message = "解析已由教师停止；本轮尚未提交的知识库变更已回滚"
            db.commit()
        update_parse_progress(job_id, status="cancelled", stage="解析已停止", error="", book_id=book_id)
        raise HTTPException(409, "教材解析已停止")
    except Exception as exc:
        db.rollback()
        failed = db.get(Book, book_id)
        if failed:
            failed.status = "failed"; failed.parse_message = str(exc)[:2000]; db.commit()
        update_parse_progress(job_id, status="failed", stage="解析失败", error=str(exc)[:500], book_id=book_id)
        raise HTTPException(422, f"教材解析失败：{exc}")


@app.get("/api/parse-progress/{job_id}")
def get_parse_progress(job_id: str, user: User = Depends(require_teacher), db: Session = Depends(get_db)):
    with PARSE_PROGRESS_LOCK:
        item = PARSE_PROGRESS.get(job_id)
        data = dict(item) if item else None
    if not data:
        raise HTTPException(404, "解析任务不存在或已过期")
    assert_course_access(db, int(data["course_id"]), user, True)
    return {key: value for key, value in data.items() if key != "user_id"}


@app.post("/api/parse-progress/{job_id}/cancel")
def cancel_parse(job_id: str, user: User = Depends(require_teacher), db: Session = Depends(get_db)):
    with PARSE_PROGRESS_LOCK:
        item = PARSE_PROGRESS.get(job_id)
        data = dict(item) if item else None
    if not data:
        raise HTTPException(404, "解析任务不存在或已过期")
    assert_course_access(db, int(data["course_id"]), user, True)
    if data.get("status") in {"completed", "failed", "cancelled"}:
        return {key: value for key, value in data.items() if key != "user_id"}
    result = update_parse_progress(
        job_id, cancel_requested=True, status="cancelling",
        stage="正在停止解析，请等待当前章节请求结束",
    )
    return {key: value for key, value in result.items() if key != "user_id"}


@app.delete("/api/books/{book_id}")
def delete_book(book_id: int, user: User = Depends(require_teacher), db: Session = Depends(get_db)):
    book = db.get(Book, book_id)
    if not book: raise HTTPException(404, "教材不存在")
    course = assert_course_access(db, book.course_id, user, True)
    topic_ids = db.scalars(select(Topic.id).where(Topic.book_id == book.id)).all()
    kp_ids = db.scalars(select(KnowledgePoint.id).where(
        KnowledgePoint.topic_id.in_(topic_ids or [-1])
    )).all()
    purge_knowledge_points(db, list(kp_ids))
    if topic_ids:
        db.execute(delete(Topic).where(Topic.id.in_(topic_ids)))
    db.execute(delete(CourseTemplateBinding).where(CourseTemplateBinding.template_book_id == book.id))
    db.delete(book)
    if kp_ids:
        course.published = False
        for resource in db.scalars(select(Resource).where(Resource.course_id == course.id)).all():
            resource.status = "waiting_for_knowledge"
            resource.parse_message = "教材已删除，上传新教材后将自动重新匹配"
    db.commit()
    file_path = Path(book.file_path)
    try:
        if file_path.resolve().is_relative_to(UPLOAD_DIR.resolve()):
            file_path.unlink(missing_ok=True)
    except OSError:
        pass
    return {"ok": True, "removed_knowledge_points": len(kp_ids)}


@app.post("/api/courses/{course_id}/resources")
def upload_resource(
    course_id: int, file: UploadFile = File(...), title: str = Form(...),
    resource_type: str = Form(...), user: User = Depends(current_user), db: Session = Depends(get_db),
):
    assert_course_access(db, course_id, user)
    teacher_types = {"ppt", "syllabus", "assignment", "exam", "note"}
    student_types = {"self_study", "book", "article", "exercise", "note"}
    allowed_types = teacher_types if user.role == "teacher" else student_types
    if resource_type not in allowed_types:
        raise HTTPException(400, "资料类型错误")
    path, digest = save_upload(file, course_id)
    resource = Resource(course_id=course_id, uploaded_by=user.id, resource_type=resource_type,
                        title=title.strip()[:240], file_path=str(path), file_hash=digest,
                        audience="course" if user.role == "teacher" else "personal")
    db.add(resource); db.commit(); db.refresh(resource)
    try:
        parsed = parse_document(path)
        if parsed.needs_ocr:
            raise ValueError(parsed.message)
        count = analyze_resource(db, resource, parsed)
        return {"id": resource.id, "evidence_count": count, "message": resource.parse_message,
                "audience": resource.audience, "analysis_engine": "ai" if llm.configured else "local"}
    except Exception as exc:
        resource.status = "failed"; resource.parse_message = str(exc); db.commit()
        raise HTTPException(422, f"资料解析失败：{exc}")


@app.get("/api/courses/{course_id}/resources")
def list_resources(course_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    assert_course_access(db, course_id, user)
    query = select(Resource).where(Resource.course_id == course_id)
    if user.role == "teacher":
        query = query.where(Resource.audience == "course")
    else:
        query = query.where(Resource.audience == "personal", Resource.uploaded_by == user.id)
    rows = db.scalars(query.order_by(Resource.id.desc())).all()
    return [{"id": r.id, "title": r.title, "type": r.resource_type, "page_count": r.page_count,
             "status": r.status, "message": r.parse_message, "audience": r.audience,
             "created_at": r.created_at.isoformat()} for r in rows]


@app.delete("/api/resources/{resource_id}")
def delete_resource(resource_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    resource = db.get(Resource, resource_id)
    if not resource:
        raise HTTPException(404, "资料不存在")
    assert_course_access(db, resource.course_id, user)
    if user.role == "teacher":
        if resource.audience != "course":
            raise HTTPException(403, "仅可管理课程教学资料")
    elif resource.audience != "personal" or resource.uploaded_by != user.id:
        raise HTTPException(403, "仅可管理自己的学习资料")
    file_path = Path(resource.file_path)
    db.execute(delete(Evidence).where(Evidence.resource_id == resource.id))
    db.delete(resource)
    db.commit()
    try:
        if file_path.resolve().is_relative_to(UPLOAD_DIR.resolve()):
            file_path.unlink(missing_ok=True)
    except OSError:
        pass
    return {"ok": True}


@app.get("/api/courses/{course_id}/knowledge")
def knowledge(course_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    assert_course_access(db, course_id, user)
    topics = active_topic_rows(db, course_id)
    reqs = {r.kp_id: r for r in db.scalars(select(CourseRequirement).where(
        CourseRequirement.course_id == course_id)).all()}
    active_ids = active_course_kp_ids(db, course_id)
    kp_query = select(KnowledgePoint).where(KnowledgePoint.course_id == course_id)
    if active_ids is not None:
        kp_query = kp_query.where(KnowledgePoint.id.in_(active_ids or {-1}))
    kps = db.scalars(kp_query.order_by(KnowledgePoint.source_page_start, KnowledgePoint.id)).all()
    visible_ids = {kp.id for kp in kps}
    rels = db.scalars(select(KnowledgeRelation).where(
        KnowledgeRelation.course_id == course_id,
        KnowledgeRelation.from_kp_id.in_(visible_ids or {-1}),
        KnowledgeRelation.to_kp_id.in_(visible_ids or {-1}),
    )).all()
    bindings = {item.kp_id: item for item in db.scalars(select(CourseKnowledgeBinding).where(
        CourseKnowledgeBinding.course_id == course_id)).all()}
    theory_counts = dict(db.execute(
        select(CanonicalTheoryBinding.canonical_point_key, func.count(CanonicalTheoryBinding.id))
        .group_by(CanonicalTheoryBinding.canonical_point_key)).all())
    material_query = select(Evidence.kp_id, func.count(Evidence.id)).where(
        Evidence.course_id == course_id, Evidence.status == "approved",
        Evidence.kp_id.in_(visible_ids or {-1}),
    )
    if user.role == "teacher":
        material_query = material_query.where(Evidence.student_id.is_(None))
    else:
        material_query = material_query.where(or_(
            Evidence.student_id.is_(None), Evidence.student_id == user.id,
        ))
    material_counts = dict(db.execute(material_query.group_by(Evidence.kp_id)).all())
    return {
        "topics": [{"id": t.id, "parent_id": t.parent_id, "title": t.title, "level": t.level,
                    "start_page": t.start_page, "end_page": t.end_page} for t in topics],
        "knowledge_points": [{
            "id": k.id, "topic_id": k.topic_id, "name": k.name, "summary": k.summary,
            "difficulty": k.difficulty, "estimated_minutes": k.estimated_minutes,
            "page_start": k.source_page_start, "page_end": k.source_page_end,
            "evidence": k.source_evidence, "confidence": k.confidence, "approved": k.approved,
            "canonical_key": bindings[k.id].canonical_key if k.id in bindings else "",
            "scope": bindings[k.id].coverage_status if k.id in bindings else "course",
            "theory_modules": theory_counts.get(bindings[k.id].canonical_key, 0) if k.id in bindings else 0,
            "material_concepts": material_counts.get(k.id, 0),
            "requirement": ({"included_in_exam": reqs[k.id].included_in_exam,
                             "required_level": reqs[k.id].required_level,
                             "exam_weight": reqs[k.id].exam_weight,
                             "ppt_emphasis": reqs[k.id].ppt_emphasis,
                             "assignment_weight": reqs[k.id].assignment_weight,
                             "teacher_note": reqs[k.id].teacher_note} if k.id in reqs else None),
        } for k in kps],
        "relations": [{"id": r.id, "from": r.from_kp_id, "to": r.to_kp_id,
                       "type": r.relation_type, "confidence": r.confidence,
                       "approved": r.approved} for r in rels],
    }


@app.get("/api/knowledge/{kp_id}/theory")
def knowledge_theory(kp_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    kp = db.get(KnowledgePoint, kp_id)
    if not kp:
        raise HTTPException(404, "知识点不存在")
    assert_course_access(db, kp.course_id, user)
    binding = db.scalar(select(CourseKnowledgeBinding).where(CourseKnowledgeBinding.kp_id == kp_id))
    modules = theory_for_canonical_point(db, binding.canonical_key) if binding else []
    evidence_query = select(Evidence).where(
        Evidence.course_id == kp.course_id, Evidence.kp_id == kp.id, Evidence.status == "approved",
    )
    if user.role == "teacher":
        evidence_query = evidence_query.where(Evidence.student_id.is_(None))
    else:
        evidence_query = evidence_query.where(or_(
            Evidence.student_id.is_(None), Evidence.student_id == user.id,
        ))
    evidence_rows = db.scalars(evidence_query.order_by(Evidence.student_id, Evidence.resource_id, Evidence.page)).all()
    resource_ids = {row.resource_id for row in evidence_rows}
    resources = {row.id: row for row in db.scalars(select(Resource).where(
        Resource.id.in_(resource_ids or {-1})
    )).all()}
    material_concepts = [{
        "id": row.id, "name": row.concept_name or kp.name,
        "summary": row.concept_summary, "excerpt": row.excerpt, "page": row.page,
        "resource": resources[row.resource_id].title if row.resource_id in resources else "资料",
        "scope": "personal" if row.student_id is not None else "course",
        "confidence": row.confidence,
    } for row in evidence_rows]
    return {"id": kp.id, "name": kp.name, "summary": kp.summary,
            "canonical_key": binding.canonical_key if binding else "", "modules": modules,
            "material_concepts": material_concepts}


@app.patch("/api/knowledge/{kp_id}")
def update_kp(kp_id: int, body: KPUpdate, user: User = Depends(require_teacher), db: Session = Depends(get_db)):
    kp = db.get(KnowledgePoint, kp_id)
    if not kp: raise HTTPException(404, "知识点不存在")
    assert_course_access(db, kp.course_id, user, True)
    for key, value in body.model_dump(exclude_none=True).items():
        if key == "name": kp.normalized_name = normalize_name(value)
        setattr(kp, key, value)
    db.commit(); return {"ok": True}


@app.delete("/api/knowledge/{kp_id}")
def delete_kp(kp_id: int, user: User = Depends(require_teacher), db: Session = Depends(get_db)):
    kp = db.get(KnowledgePoint, kp_id)
    if not kp: raise HTTPException(404, "知识点不存在")
    course = assert_course_access(db, kp.course_id, user, True)
    purge_knowledge_points(db, [kp.id])
    remaining = db.scalar(select(func.count()).select_from(KnowledgePoint).where(
        KnowledgePoint.course_id == course.id, KnowledgePoint.approved.is_(True)
    ))
    if not remaining:
        course.published = False
    db.commit()
    return {"ok": True}


@app.post("/api/courses/{course_id}/knowledge/approve-all")
def approve_all(course_id: int, user: User = Depends(require_teacher), db: Session = Depends(get_db)):
    assert_course_access(db, course_id, user, True)
    active_ids = active_course_kp_ids(db, course_id)
    kp_query = select(KnowledgePoint).where(KnowledgePoint.course_id == course_id)
    if active_ids is not None:
        kp_query = kp_query.where(KnowledgePoint.id.in_(active_ids or {-1}))
    kps = db.scalars(kp_query).all()
    visible_ids = {kp.id for kp in kps}
    rels = db.scalars(select(KnowledgeRelation).where(
        KnowledgeRelation.course_id == course_id,
        KnowledgeRelation.from_kp_id.in_(visible_ids or {-1}),
        KnowledgeRelation.to_kp_id.in_(visible_ids or {-1}),
    )).all()
    for kp in kps: kp.approved = True
    for rel in rels: rel.approved = True
    current_book = db.scalar(select(Book).where(
        Book.course_id == course_id, Book.status == "needs_review"
    ).order_by(Book.id.desc()))
    if current_book:
        current_book.status = "ready"
    # Ensure every enrolled student gets states for newly approved nodes.
    students = db.scalars(select(Enrollment).where(Enrollment.course_id == course_id)).all()
    for e in students:
        existing = {x.kp_id for x in db.scalars(select(StudentState).where(StudentState.student_id == e.student_id)).all()}
        for kp in kps:
            if kp.id not in existing: db.add(StudentState(student_id=e.student_id, kp_id=kp.id))
    db.commit(); return {"knowledge_points": len(kps), "relations": len(rels)}


@app.post("/api/courses/{course_id}/relations")
def add_relation(course_id: int, body: RelationBody, user: User = Depends(require_teacher), db: Session = Depends(get_db)):
    assert_course_access(db, course_id, user, True)
    if body.from_kp_id == body.to_kp_id: raise HTTPException(400, "知识点不可依赖自身")
    for kp_id in (body.from_kp_id, body.to_kp_id):
        kp = db.get(KnowledgePoint, kp_id)
        if not kp or kp.course_id != course_id: raise HTTPException(400, "关系节点不属于该课程")
    # A prerequisite graph must remain acyclic.  Adding A -> B creates a cycle
    # exactly when B can already reach A through existing approved relations.
    adjacency: dict[int, list[int]] = {}
    for existing in db.scalars(select(KnowledgeRelation).where(
        KnowledgeRelation.course_id == course_id,
    )):
        adjacency.setdefault(existing.from_kp_id, []).append(existing.to_kp_id)
    stack, visited = [body.to_kp_id], set()
    while stack:
        node = stack.pop()
        if node == body.from_kp_id:
            raise HTTPException(409, "该关系会形成循环依赖")
        if node not in visited:
            visited.add(node)
            stack.extend(adjacency.get(node, []))
    rel = KnowledgeRelation(course_id=course_id, **body.model_dump(), confidence=1.0)
    db.add(rel)
    try: db.commit()
    except Exception:
        db.rollback(); raise HTTPException(409, "关系已存在")
    return {"id": rel.id}


@app.delete("/api/relations/{relation_id}")
def delete_relation(relation_id: int, user: User = Depends(require_teacher), db: Session = Depends(get_db)):
    rel = db.get(KnowledgeRelation, relation_id)
    if not rel: raise HTTPException(404, "关系不存在")
    assert_course_access(db, rel.course_id, user, True)
    db.delete(rel); db.commit(); return {"ok": True}


@app.patch("/api/requirements/{kp_id}")
def update_requirement(kp_id: int, body: RequirementBody, user: User = Depends(require_teacher), db: Session = Depends(get_db)):
    kp = db.get(KnowledgePoint, kp_id)
    if not kp: raise HTTPException(404, "知识点不存在")
    assert_course_access(db, kp.course_id, user, True)
    req = db.scalar(select(CourseRequirement).where(CourseRequirement.kp_id == kp_id,
                                                     CourseRequirement.course_id == kp.course_id))
    if not req: req = CourseRequirement(kp_id=kp_id, course_id=kp.course_id); db.add(req)
    for key, value in body.model_dump(exclude_none=True).items(): setattr(req, key, value)
    db.commit(); return {"ok": True}


@app.get("/api/courses/{course_id}/evidence")
def list_evidence(course_id: int, status: str = "pending", user: User = Depends(require_teacher), db: Session = Depends(get_db)):
    assert_course_access(db, course_id, user, True)
    q = select(Evidence).where(Evidence.course_id == course_id, Evidence.student_id.is_(None))
    if status != "all": q = q.where(Evidence.status == status)
    rows = db.scalars(q.order_by(Evidence.confidence.desc(), Evidence.id)).all()
    kp_names = {k.id: k.name for k in db.scalars(select(KnowledgePoint).where(KnowledgePoint.course_id == course_id)).all()}
    resource_names = {r.id: r.title for r in db.scalars(select(Resource).where(Resource.course_id == course_id)).all()}
    topic_names = dict(db.execute(select(KnowledgePoint.id, Topic.title).join(
        Topic, Topic.id == KnowledgePoint.topic_id
    ).where(KnowledgePoint.course_id == course_id)).all())
    return [{"id": e.id, "kp_id": e.kp_id, "kp_name": kp_names.get(e.kp_id, "?"),
             "resource": resource_names.get(e.resource_id, "?"), "page": e.page,
             "excerpt": e.excerpt, "effect_type": e.effect_type,
             "suggested_value": e.suggested_value, "confidence": e.confidence,
             "status": e.status, "concept_name": e.concept_name or kp_names.get(e.kp_id, "?"),
             "concept_summary": e.concept_summary, "match_method": e.match_method,
             "topic_name": topic_names.get(e.kp_id, "课程内容")} for e in rows]


@app.get("/api/courses/{course_id}/personal-evidence")
def list_personal_evidence(course_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.role != "student":
        raise HTTPException(403, "此页面面向学生")
    assert_course_access(db, course_id, user)
    rows = db.scalars(select(Evidence).where(
        Evidence.course_id == course_id, Evidence.student_id == user.id,
        Evidence.status == "approved",
    ).order_by(Evidence.resource_id.desc(), Evidence.page, Evidence.id)).all()
    kp_rows = db.execute(select(KnowledgePoint.id, KnowledgePoint.name, Topic.title).join(
        Topic, Topic.id == KnowledgePoint.topic_id
    ).where(KnowledgePoint.course_id == course_id)).all()
    kp_names = {row[0]: row[1] for row in kp_rows}
    topic_names = {row[0]: row[2] for row in kp_rows}
    resources = {r.id: r.title for r in db.scalars(select(Resource).where(
        Resource.course_id == course_id, Resource.audience == "personal",
        Resource.uploaded_by == user.id,
    )).all()}
    return [{
        "id": e.id, "resource_id": e.resource_id, "resource": resources.get(e.resource_id, "?"),
        "kp_id": e.kp_id, "kp_name": kp_names.get(e.kp_id, "?"),
        "topic_name": topic_names.get(e.kp_id, "课程内容"), "page": e.page,
        "concept_name": e.concept_name or kp_names.get(e.kp_id, "?"),
        "concept_summary": e.concept_summary, "excerpt": e.excerpt,
        "confidence": e.confidence, "match_method": e.match_method,
    } for e in rows if e.resource_id in resources]


@app.post("/api/evidence/{evidence_id}/review")
def review_evidence(evidence_id: int, approve: bool, user: User = Depends(require_teacher), db: Session = Depends(get_db)):
    row = db.get(Evidence, evidence_id)
    if not row: raise HTTPException(404, "证据不存在")
    assert_course_access(db, row.course_id, user, True)
    if row.student_id is not None:
        raise HTTPException(403, "个人学习资料无需课程审核")
    apply_evidence(db, row, approve); return {"ok": True}


@app.post("/api/courses/{course_id}/evidence/review-all")
def review_all_evidence(course_id: int, approve: bool = True, user: User = Depends(require_teacher),
                        db: Session = Depends(get_db)):
    assert_course_access(db, course_id, user, True)
    rows = db.scalars(select(Evidence).where(
        Evidence.course_id == course_id, Evidence.status == "pending", Evidence.student_id.is_(None)
    )).all()
    for row in rows:
        apply_evidence(db, row, approve)
    return {"reviewed": len(rows), "status": "approved" if approve else "rejected"}


@app.get("/api/courses/{course_id}/states")
def states(course_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    assert_course_access(db, course_id, user)
    student_id = user.id
    active_ids = active_course_kp_ids(db, course_id)
    query = select(KnowledgePoint).where(KnowledgePoint.course_id == course_id,
                                         KnowledgePoint.approved == True)  # noqa: E712
    if active_ids is not None:
        query = query.where(KnowledgePoint.id.in_(active_ids or {-1}))
    kps = db.scalars(query).all()
    rows = {s.kp_id: s for s in db.scalars(select(StudentState).where(
        StudentState.student_id == student_id)).all()}
    return [{"kp_id": k.id, "name": k.name, "mastery": rows[k.id].mastery if k.id in rows else 0.25,
             "retention": retention(rows.get(k.id)), "review_count": rows[k.id].review_count if k.id in rows else 0}
            for k in kps]


@app.put("/api/states/{kp_id}")
def set_state(kp_id: int, body: StateBody, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.role != "student": raise HTTPException(400, "教师不维护学生掌握状态")
    kp = db.get(KnowledgePoint, kp_id)
    if not kp: raise HTTPException(404, "知识点不存在")
    assert_course_access(db, kp.course_id, user)
    state = db.scalar(select(StudentState).where(StudentState.student_id == user.id,
                                                 StudentState.kp_id == kp_id))
    if not state: state = StudentState(student_id=user.id, kp_id=kp_id); db.add(state)
    state.mastery = max(0.0, min(1.0, body.mastery)); db.commit(); return {"ok": True}


def plan_payload(db: Session, plan: StudyPlan):
    items = db.scalars(select(PlanItem).where(PlanItem.plan_id == plan.id).order_by(
        PlanItem.day_index, PlanItem.id)).all()
    names = {k.id: k.name for k in db.scalars(select(KnowledgePoint).where(
        KnowledgePoint.id.in_([x.kp_id for x in items] or [-1]))).all()}
    days = max(1, (date.fromisoformat(plan.exam_date) - date.today()).days + 1)
    total_minutes = sum(x.minutes for x in items)
    capacity_minutes = days * plan.daily_minutes
    overloaded = ideal_total_minutes(db, plan.course_id, plan.student_id) > capacity_minutes
    return {"id": plan.id, "exam_date": plan.exam_date, "daily_minutes": plan.daily_minutes,
            "days": days, "total_minutes": total_minutes, "capacity_minutes": capacity_minutes,
            "overloaded": overloaded,
            "created_at": plan.created_at.isoformat(), "items": [{"id": x.id, "kp_id": x.kp_id,
            "name": names.get(x.kp_id, "?"), "day": x.day_index, "minutes": x.minutes,
            "priority": x.priority, "reason": x.reason, "completed": x.completed} for x in items]}


@app.post("/api/courses/{course_id}/plans")
def create_plan(course_id: int, body: PlanBody, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.role != "student": raise HTTPException(400, "学习计划由学生生成")
    assert_course_access(db, course_id, user)
    try: exam = date.fromisoformat(body.exam_date)
    except ValueError: raise HTTPException(400, "考试日期格式错误")
    if exam < date.today(): raise HTTPException(400, "考试日期需为今天或未来日期")
    plan = generate_plan(db, course_id, user.id, body.exam_date, body.daily_minutes)
    return plan_payload(db, plan)


@app.get("/api/courses/{course_id}/plans/current")
def current_plan(course_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.role != "student": raise HTTPException(400, "学习计划由学生使用")
    assert_course_access(db, course_id, user)
    plan = db.scalar(select(StudyPlan).where(StudyPlan.course_id == course_id,
                                             StudyPlan.student_id == user.id).order_by(StudyPlan.id.desc()))
    return plan_payload(db, plan) if plan else None


@app.post("/api/plan-items/{item_id}/complete")
def complete_item(item_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    item = db.get(PlanItem, item_id)
    if not item: raise HTTPException(404, "计划项不存在")
    plan = db.get(StudyPlan, item.plan_id)
    if not plan or plan.student_id != user.id: raise HTTPException(403, "无权修改")
    item.completed = not item.completed; db.commit(); return {"completed": item.completed}


@app.get("/api/courses/{course_id}/quiz")
def quiz(course_id: int, count: int = 5, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.role != "student": raise HTTPException(400, "诊断测验由学生使用")
    assert_course_access(db, course_id, user)
    states = {s.kp_id: s for s in db.scalars(select(StudentState).where(StudentState.student_id == user.id)).all()}
    active_ids = active_course_kp_ids(db, course_id)
    questions = list(db.scalars(select(DiagnosticQuestion).where(
        DiagnosticQuestion.course_id == course_id,
        DiagnosticQuestion.active.is_(True),
    )).all())
    answer_ids = set(db.scalars(select(DiagnosticAnswerKey.diagnostic_question_id).where(
        DiagnosticAnswerKey.diagnostic_question_id.in_([x.id for x in questions] or [-1])
    )).all())
    if not questions or len(answer_ids) != len(questions):
        rebuild_question_bank(db, course_id, active_ids, refresh_sources=False)
        questions = list(db.scalars(select(DiagnosticQuestion).where(
            DiagnosticQuestion.course_id == course_id,
            DiagnosticQuestion.active.is_(True),
        )).all())
    if active_ids is not None:
        questions = [q for q in questions if q.kp_id in active_ids]
    kps = {k.id: k for k in db.scalars(select(KnowledgePoint).where(
        KnowledgePoint.course_id == course_id,
        KnowledgePoint.approved.is_(True),
    )).all()}
    questions = [q for q in questions if q.kp_id in kps]
    grouped_questions: dict[int, list[DiagnosticQuestion]] = {}
    for item in questions:
        grouped_questions.setdefault(item.kp_id, []).append(item)
    kp_order = sorted(grouped_questions, key=lambda kp_id: (
        (states[kp_id].mastery if kp_id in states else 0.25)
        - 0.30 * max(x.focus_score for x in grouped_questions[kp_id]),
        kp_id,
    ))
    diversified = []
    round_index = 0
    while len(diversified) < len(questions):
        added = False
        for kp_id in kp_order:
            bucket = grouped_questions[kp_id]
            if round_index < len(bucket):
                diversified.append(bucket[round_index]); added = True
        if not added:
            break
        round_index += 1
    questions = diversified
    return [{
        "question_id": q.id,
        "kp_id": q.kp_id,
        "kp_name": kps[q.kp_id].name,
        "chapter": q.chapter_title,
        "question": "请判断下面的说法是否正确。",
        "statement": q.statement,
        "prompt": q.rationale,
        "focus_score": q.focus_score,
        "source": q.source,
        "response_mode": "judgment",
    } for q in questions[:max(1, min(30, count))]]


@app.post("/api/quiz/submit")
def submit_quiz(body: QuizSubmit, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.role != "student": raise HTTPException(400, "只有学生提交测验")
    kp = db.get(KnowledgePoint, body.kp_id)
    if not kp: raise HTTPException(404, "知识点不存在")
    assert_course_access(db, kp.course_id, user)
    selected = body.judgment if body.judgment is not None else body.correct
    if selected is None:
        raise HTTPException(422, "请选择正确或错误")
    if body.question_id is None:
        raise HTTPException(422, "判断题缺少题目编号")
    item = db.get(DiagnosticQuestion, body.question_id)
    if not item or item.kp_id != kp.id or item.course_id != kp.course_id:
        raise HTTPException(400, "诊断题与知识点不匹配")
    key = db.scalar(select(DiagnosticAnswerKey).where(
        DiagnosticAnswerKey.diagnostic_question_id == item.id))
    if not key:
        raise HTTPException(409, "本题答案键待重建")
    is_correct = selected == key.correct_answer
    state = db.scalar(select(StudentState).where(StudentState.student_id == user.id,
                                                 StudentState.kp_id == kp.id))
    if not state: state = StudentState(student_id=user.id, kp_id=kp.id); db.add(state); db.flush()
    update_mastery(state, is_correct)
    db.add(QuizAttempt(student_id=user.id, kp_id=kp.id, question=body.question,
                       answer=body.answer or ("正确" if selected else "错误"), correct=is_correct))
    db.commit(); return {"mastery": state.mastery, "stability": state.stability,
                         "correct": is_correct, "correct_answer": key.correct_answer,
                         "explanation": key.explanation}


@app.get("/api/courses/{course_id}/question-bank")
def question_bank(course_id: int, user: User = Depends(require_teacher), db: Session = Depends(get_db)):
    assert_course_access(db, course_id, user, True)
    rows = list(db.scalars(select(DiagnosticQuestion).where(
        DiagnosticQuestion.course_id == course_id,
    ).order_by(DiagnosticQuestion.chapter_title, DiagnosticQuestion.focus_score.desc(),
               DiagnosticQuestion.id)).all())
    source_pool = dict(db.execute(select(QuestionSourceItem.source_code, func.count()).group_by(
        QuestionSourceItem.source_code)).all())
    source_counts: dict[str, int] = {}
    for item in rows:
        source_counts[item.source] = source_counts.get(item.source, 0) + 1
    keys = {x.diagnostic_question_id: x for x in db.scalars(select(DiagnosticAnswerKey).where(
        DiagnosticAnswerKey.diagnostic_question_id.in_([x.id for x in rows] or [-1]))).all()}
    return {
        "count": len(rows),
        "source_counts": source_counts,
        "source_pool": source_pool,
        "chapters": len({x.chapter_title for x in rows}),
        "llm_configured": llm.configured,
        "questions": [{
            "id": x.id, "kp_id": x.kp_id, "chapter": x.chapter_title,
            "statement": x.statement, "rationale": x.rationale,
            "source": x.source, "focus_score": x.focus_score,
            "difficulty": x.difficulty, "active": x.active,
            "correct_answer": keys[x.id].correct_answer if x.id in keys else None,
            "explanation": keys[x.id].explanation if x.id in keys else "",
        } for x in rows],
    }


@app.post("/api/courses/{course_id}/question-bank/generate")
def generate_question_bank(course_id: int, user: User = Depends(require_teacher), db: Session = Depends(get_db)):
    assert_course_access(db, course_id, user, True)
    return rebuild_question_bank(db, course_id, active_course_kp_ids(db, course_id), refresh_sources=True)


@app.delete("/api/question-bank/{question_id}")
def delete_question(question_id: int, user: User = Depends(require_teacher), db: Session = Depends(get_db)):
    item = db.get(DiagnosticQuestion, question_id)
    if not item:
        raise HTTPException(404, "诊断题不存在")
    assert_course_access(db, item.course_id, user, True)
    db.execute(delete(DiagnosticAnswerKey).where(
        DiagnosticAnswerKey.diagnostic_question_id == item.id))
    db.delete(item); db.commit()
    return {"deleted": True}


@app.get("/api/courses/{course_id}/teacher-overview")
def teacher_overview(course_id: int, user: User = Depends(require_teacher), db: Session = Depends(get_db)):
    assert_course_access(db, course_id, user, True)
    enrollments = db.scalars(select(Enrollment).where(Enrollment.course_id == course_id)).all()
    student_ids = [e.student_id for e in enrollments]
    states = db.scalars(select(StudentState).where(StudentState.student_id.in_(student_ids or [-1]))).all()
    active_ids = active_course_kp_ids(db, course_id)
    query = select(KnowledgePoint).where(KnowledgePoint.course_id == course_id,
                                         KnowledgePoint.approved == True)  # noqa: E712
    if active_ids is not None:
        query = query.where(KnowledgePoint.id.in_(active_ids or {-1}))
    kps = db.scalars(query).all()
    kp_names = {k.id: k.name for k in kps}
    grouped = {k.id: [] for k in kps}
    for s in states:
        if s.kp_id in grouped: grouped[s.kp_id].append(s.mastery)
    weak = [{"kp_id": kp_id, "name": kp_names[kp_id], "avg_mastery": sum(vals)/len(vals) if vals else 0,
             "student_count": len(vals)} for kp_id, vals in grouped.items()]
    weak.sort(key=lambda x: x["avg_mastery"])
    pending = db.scalar(select(func.count()).select_from(Evidence).where(Evidence.course_id == course_id,
                                                                          Evidence.status == "pending"))
    return {"students": len(student_ids), "knowledge_points": len(kps), "pending_evidence": pending,
            "average_mastery": sum(s.mastery for s in states)/len(states) if states else 0,
            "weak_points": weak[:10]}


app.mount("/assets", StaticFiles(directory=STATIC), name="assets")


@app.get("/{full_path:path}", include_in_schema=False)
def spa(full_path: str):
    path = STATIC / full_path
    if full_path and path.is_file(): return FileResponse(path)
    return FileResponse(STATIC / "index.html")
