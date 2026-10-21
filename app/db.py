from __future__ import annotations

from datetime import UTC, datetime
import os
from pathlib import Path

from sqlalchemy import (
    Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint,
    create_engine, text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DB_PATH = Path(os.getenv("STUDYSHIP_DB_PATH", str(DATA_DIR / "studyship.db")))
UPLOAD_DIR = Path(os.getenv("STUDYSHIP_UPLOAD_DIR", str(DATA_DIR / "uploads")))
DATA_DIR.mkdir(exist_ok=True)
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    f"sqlite:///{DB_PATH.as_posix()}",
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def utcnow() -> datetime:
    """Return naive UTC for SQLite while avoiding deprecated utcnow()."""
    return datetime.now(UTC).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    display_name: Mapped[str] = mapped_column(String(80))
    role: Mapped[str] = mapped_column(String(20), default="student")
    student_no: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class SessionToken(Base):
    __tablename__ = "session_tokens"
    id: Mapped[int] = mapped_column(primary_key=True)
    token: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    expires_at: Mapped[datetime] = mapped_column(DateTime)


class Course(Base):
    __tablename__ = "courses"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    code: Mapped[str] = mapped_column(String(40), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    academic_year: Mapped[str] = mapped_column(String(30), default="2026-2027")
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    published: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Enrollment(Base):
    __tablename__ = "enrollments"
    __table_args__ = (UniqueConstraint("course_id", "student_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"))
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    enrolled_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Book(Base):
    __tablename__ = "books"
    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    author: Mapped[str] = mapped_column(String(120), default="")
    publisher: Mapped[str] = mapped_column(String(120), default="")
    edition: Mapped[str] = mapped_column(String(60), default="")
    isbn: Mapped[str] = mapped_column(String(40), default="")
    file_path: Mapped[str] = mapped_column(Text)
    file_hash: Mapped[str] = mapped_column(String(64), index=True)
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(30), default="uploaded")
    parse_message: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Topic(Base):
    __tablename__ = "topics"
    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"))
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("topics.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(240))
    level: Mapped[int] = mapped_column(Integer, default=1)
    start_page: Mapped[int] = mapped_column(Integer, default=1)
    end_page: Mapped[int] = mapped_column(Integer, default=1)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class KnowledgePoint(Base):
    __tablename__ = "knowledge_points"
    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    topic_id: Mapped[int | None] = mapped_column(ForeignKey("topics.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(240))
    normalized_name: Mapped[str] = mapped_column(String(240), index=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    difficulty: Mapped[int] = mapped_column(Integer, default=2)
    estimated_minutes: Mapped[int] = mapped_column(Integer, default=45)
    source_page_start: Mapped[int] = mapped_column(Integer, default=1)
    source_page_end: Mapped[int] = mapped_column(Integer, default=1)
    source_evidence: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    approved: Mapped[bool] = mapped_column(Boolean, default=False)


class KnowledgeRelation(Base):
    __tablename__ = "knowledge_relations"
    __table_args__ = (UniqueConstraint("course_id", "from_kp_id", "to_kp_id", "relation_type"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    from_kp_id: Mapped[int] = mapped_column(ForeignKey("knowledge_points.id", ondelete="CASCADE"))
    to_kp_id: Mapped[int] = mapped_column(ForeignKey("knowledge_points.id", ondelete="CASCADE"))
    relation_type: Mapped[str] = mapped_column(String(30), default="prerequisite")
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    approved: Mapped[bool] = mapped_column(Boolean, default=False)


class CurriculumTemplate(Base):
    __tablename__ = "curriculum_templates"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    version: Mapped[str] = mapped_column(String(40))
    description: Mapped[str] = mapped_column(Text, default="")
    source_note: Mapped[str] = mapped_column(Text, default="")


class CanonicalTopic(Base):
    __tablename__ = "canonical_topics"
    __table_args__ = (UniqueConstraint("template_id", "canonical_key"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    template_id: Mapped[int] = mapped_column(ForeignKey("curriculum_templates.id", ondelete="CASCADE"), index=True)
    canonical_key: Mapped[str] = mapped_column(String(100), index=True)
    parent_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    title: Mapped[str] = mapped_column(String(240))
    aliases: Mapped[str] = mapped_column(Text, default="")
    level: Mapped[int] = mapped_column(Integer, default=1)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class CanonicalKnowledgePoint(Base):
    __tablename__ = "canonical_knowledge_points"
    __table_args__ = (UniqueConstraint("template_id", "canonical_key"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    template_id: Mapped[int] = mapped_column(ForeignKey("curriculum_templates.id", ondelete="CASCADE"), index=True)
    canonical_key: Mapped[str] = mapped_column(String(120), index=True)
    topic_key: Mapped[str] = mapped_column(String(100), index=True)
    name: Mapped[str] = mapped_column(String(240))
    aliases: Mapped[str] = mapped_column(Text, default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    point_type: Mapped[str] = mapped_column(String(30), default="core")
    difficulty: Mapped[int] = mapped_column(Integer, default=2)
    estimated_minutes: Mapped[int] = mapped_column(Integer, default=45)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class CanonicalRelation(Base):
    __tablename__ = "canonical_relations"
    __table_args__ = (UniqueConstraint("template_id", "from_key", "to_key", "relation_type"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    template_id: Mapped[int] = mapped_column(ForeignKey("curriculum_templates.id", ondelete="CASCADE"), index=True)
    from_key: Mapped[str] = mapped_column(String(120))
    to_key: Mapped[str] = mapped_column(String(120))
    relation_type: Mapped[str] = mapped_column(String(30), default="prerequisite")


class CourseTemplateBinding(Base):
    __tablename__ = "course_template_bindings"
    __table_args__ = (UniqueConstraint("course_id", "template_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    template_id: Mapped[int] = mapped_column(ForeignKey("curriculum_templates.id", ondelete="CASCADE"))
    template_book_id: Mapped[int] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class CourseKnowledgeBinding(Base):
    __tablename__ = "course_knowledge_bindings"
    __table_args__ = (UniqueConstraint("course_id", "canonical_key"), UniqueConstraint("kp_id"))
    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    kp_id: Mapped[int] = mapped_column(ForeignKey("knowledge_points.id", ondelete="CASCADE"), index=True)
    canonical_key: Mapped[str] = mapped_column(String(120), index=True)
    coverage_status: Mapped[str] = mapped_column(String(30), default="pending")
    matched_outline_title: Mapped[str] = mapped_column(String(240), default="")
    match_confidence: Mapped[float] = mapped_column(Float, default=0.0)


class OutlineDocument(Base):
    __tablename__ = "outline_documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(240))
    file_path: Mapped[str] = mapped_column(Text, default="")
    file_hash: Mapped[str] = mapped_column(String(64), default="")
    raw_text: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(30), default="needs_review")
    parse_message: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class OutlineEntry(Base):
    __tablename__ = "outline_entries"
    id: Mapped[int] = mapped_column(primary_key=True)
    outline_id: Mapped[int] = mapped_column(ForeignKey("outline_documents.id", ondelete="CASCADE"), index=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("outline_entries.id", ondelete="CASCADE"), nullable=True)
    title: Mapped[str] = mapped_column(String(240))
    normalized_title: Mapped[str] = mapped_column(String(240), index=True)
    level: Mapped[int] = mapped_column(Integer, default=1)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    matched_topic_key: Mapped[str] = mapped_column(String(100), default="")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    review_status: Mapped[str] = mapped_column(String(30), default="pending")


class CourseOutlineBinding(Base):
    """Connect one parsed local outline to the concrete course chapter tree."""
    __tablename__ = "course_outline_bindings"
    __table_args__ = (UniqueConstraint("outline_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    outline_id: Mapped[int] = mapped_column(ForeignKey("outline_documents.id", ondelete="CASCADE"), index=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id", ondelete="CASCADE"))
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class TheorySource(Base):
    __tablename__ = "theory_sources"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    version: Mapped[str] = mapped_column(String(80), default="master")
    repository_url: Mapped[str] = mapped_column(Text, default="")
    imported_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    module_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(30), default="ready")
    message: Mapped[str] = mapped_column(Text, default="")


class TheoryModule(Base):
    __tablename__ = "theory_modules"
    __table_args__ = (UniqueConstraint("source_id", "module_key"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("theory_sources.id", ondelete="CASCADE"), index=True)
    module_key: Mapped[str] = mapped_column(String(180), index=True)
    title: Mapped[str] = mapped_column(String(300))
    source_path: Mapped[str] = mapped_column(Text)
    source_url: Mapped[str] = mapped_column(Text, default="")
    content_hash: Mapped[str] = mapped_column(String(64), default="")
    raw_rst: Mapped[str] = mapped_column(Text, default="")
    plain_text: Mapped[str] = mapped_column(Text, default="")
    imported_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class TheorySection(Base):
    __tablename__ = "theory_sections"
    __table_args__ = (UniqueConstraint("module_id", "sort_order"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    module_id: Mapped[int] = mapped_column(ForeignKey("theory_modules.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    level: Mapped[int] = mapped_column(Integer, default=1)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    body: Mapped[str] = mapped_column(Text, default="")


class CanonicalTheoryBinding(Base):
    __tablename__ = "canonical_theory_bindings"
    __table_args__ = (UniqueConstraint("canonical_point_key", "module_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    canonical_point_key: Mapped[str] = mapped_column(String(120), index=True)
    module_id: Mapped[int] = mapped_column(ForeignKey("theory_modules.id", ondelete="CASCADE"), index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=True)


class Resource(Base):
    __tablename__ = "resources"
    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    uploaded_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    resource_type: Mapped[str] = mapped_column(String(30))
    title: Mapped[str] = mapped_column(String(240))
    file_path: Mapped[str] = mapped_column(Text)
    file_hash: Mapped[str] = mapped_column(String(64))
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    extracted_text: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(30), default="uploaded")
    parse_message: Mapped[str] = mapped_column(Text, default="")
    # course: teacher-owned shared material; personal: visible only to its student owner.
    audience: Mapped[str] = mapped_column(String(20), default="course", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Evidence(Base):
    __tablename__ = "evidence"
    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    resource_id: Mapped[int] = mapped_column(ForeignKey("resources.id", ondelete="CASCADE"))
    kp_id: Mapped[int] = mapped_column(ForeignKey("knowledge_points.id", ondelete="CASCADE"))
    page: Mapped[int] = mapped_column(Integer, default=1)
    excerpt: Mapped[str] = mapped_column(Text)
    effect_type: Mapped[str] = mapped_column(String(40))
    suggested_value: Mapped[float] = mapped_column(Float)
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    # Personal evidence enriches one student's view without changing the shared graph.
    student_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    concept_name: Mapped[str] = mapped_column(String(240), default="")
    concept_summary: Mapped[str] = mapped_column(Text, default="")
    match_method: Mapped[str] = mapped_column(String(30), default="literal")


class CourseRequirement(Base):
    __tablename__ = "course_requirements"
    __table_args__ = (UniqueConstraint("course_id", "kp_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    kp_id: Mapped[int] = mapped_column(ForeignKey("knowledge_points.id", ondelete="CASCADE"))
    included_in_exam: Mapped[bool] = mapped_column(Boolean, default=True)
    required_level: Mapped[int] = mapped_column(Integer, default=2)
    exam_weight: Mapped[float] = mapped_column(Float, default=0.5)
    ppt_emphasis: Mapped[float] = mapped_column(Float, default=0.0)
    assignment_weight: Mapped[float] = mapped_column(Float, default=0.0)
    exam_frequency: Mapped[float] = mapped_column(Float, default=0.0)
    teacher_note: Mapped[str] = mapped_column(Text, default="")


class StudentState(Base):
    __tablename__ = "student_states"
    __table_args__ = (UniqueConstraint("student_id", "kp_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kp_id: Mapped[int] = mapped_column(ForeignKey("knowledge_points.id", ondelete="CASCADE"))
    mastery: Mapped[float] = mapped_column(Float, default=0.25)
    stability: Mapped[float] = mapped_column(Float, default=3.0)
    review_count: Mapped[int] = mapped_column(Integer, default=0)
    last_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    quiz_correct: Mapped[int] = mapped_column(Integer, default=0)
    quiz_total: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class StudyPlan(Base):
    __tablename__ = "study_plans"
    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"))
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    exam_date: Mapped[str] = mapped_column(String(20))
    daily_minutes: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class PlanItem(Base):
    __tablename__ = "plan_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("study_plans.id", ondelete="CASCADE"), index=True)
    kp_id: Mapped[int] = mapped_column(ForeignKey("knowledge_points.id"))
    day_index: Mapped[int] = mapped_column(Integer)
    minutes: Mapped[int] = mapped_column(Integer)
    priority: Mapped[float] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(Text)
    completed: Mapped[bool] = mapped_column(Boolean, default=False)


class QuestionSourceItem(Base):
    """Normalized exercise mirrored from a reviewed external course source."""
    __tablename__ = "question_source_items"
    __table_args__ = (UniqueConstraint("source_code", "source_ref"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    source_code: Mapped[str] = mapped_column(String(40), index=True)
    source_ref: Mapped[str] = mapped_column(String(600))
    source_group: Mapped[str] = mapped_column(String(160), default="")
    question_text: Mapped[str] = mapped_column(Text)
    answer_text: Mapped[str] = mapped_column(Text, default="")
    explanation: Mapped[str] = mapped_column(Text, default="")
    familiarity_statement: Mapped[str] = mapped_column(Text)
    difficulty: Mapped[int] = mapped_column(Integer, default=2)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class SourceJudgment(Base):
    """An atomic true/false proposition mined from one mirrored source exercise."""
    __tablename__ = "source_judgments"
    id: Mapped[int] = mapped_column(primary_key=True)
    source_item_id: Mapped[int] = mapped_column(
        ForeignKey("question_source_items.id", ondelete="CASCADE"), unique=True, index=True,
    )
    statement: Mapped[str] = mapped_column(Text)
    correct_answer: Mapped[bool] = mapped_column(Boolean)
    explanation: Mapped[str] = mapped_column(Text, default="")
    concept_label: Mapped[str] = mapped_column(String(240), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class DiagnosticQuestion(Base):
    """A persisted true/false judgment mapped to a course knowledge point."""
    __tablename__ = "diagnostic_questions"
    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    kp_id: Mapped[int] = mapped_column(ForeignKey("knowledge_points.id", ondelete="CASCADE"), index=True)
    chapter_topic_id: Mapped[int | None] = mapped_column(ForeignKey("topics.id"), nullable=True)
    chapter_title: Mapped[str] = mapped_column(String(240), default="课程核心知识")
    statement: Mapped[str] = mapped_column(Text)
    rationale: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(30), default="local")
    focus_score: Mapped[float] = mapped_column(Float, default=0.5)
    difficulty: Mapped[int] = mapped_column(Integer, default=2)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class DiagnosticAnswerKey(Base):
    """Teacher-side key kept separate so quiz delivery never exposes the answer."""
    __tablename__ = "diagnostic_answer_keys"
    id: Mapped[int] = mapped_column(primary_key=True)
    diagnostic_question_id: Mapped[int] = mapped_column(
        ForeignKey("diagnostic_questions.id", ondelete="CASCADE"), unique=True, index=True,
    )
    correct_answer: Mapped[bool] = mapped_column(Boolean)
    explanation: Mapped[str] = mapped_column(Text, default="")
    source_judgment_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class QuizAttempt(Base):
    __tablename__ = "quiz_attempts"
    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kp_id: Mapped[int] = mapped_column(ForeignKey("knowledge_points.id", ondelete="CASCADE"))
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text, default="")
    correct: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


def create_all() -> None:
    Base.metadata.create_all(engine)
    # Lightweight in-place migration for installations created before personal
    # learning resources were introduced.  SQLite keeps existing user data and
    # new databases already contain these columns through metadata.create_all().
    migrations = {
        "resources": {
            "audience": "VARCHAR(20) NOT NULL DEFAULT 'course'",
        },
        "evidence": {
            "student_id": "INTEGER",
            "concept_name": "VARCHAR(240) NOT NULL DEFAULT ''",
            "concept_summary": "TEXT NOT NULL DEFAULT ''",
            "match_method": "VARCHAR(30) NOT NULL DEFAULT 'literal'",
        },
    }
    with engine.begin() as connection:
        for table, columns in migrations.items():
            existing = {row[1] for row in connection.execute(text(f"PRAGMA table_info({table})"))}
            for column, definition in columns.items():
                if column not in existing:
                    connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {definition}"))
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_resources_audience ON resources (audience)"
        ))
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_evidence_student_id ON evidence (student_id)"
        ))
