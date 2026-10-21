from __future__ import annotations

import math
import heapq
from collections import defaultdict
from datetime import date, datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..db import (
    CourseRequirement, KnowledgePoint, KnowledgeRelation, PlanItem, StudentState, StudyPlan,
    utcnow,
)


def retention(state: StudentState | None, now: datetime | None = None) -> float:
    if not state or state.review_count <= 0 or not state.last_reviewed_at:
        return 1.0
    now = now or utcnow()
    days = max(0.0, (now - state.last_reviewed_at).total_seconds() / 86400)
    return math.exp(-days / max(0.25, state.stability))


def topological_order(kps, relations, priorities=None):
    priorities = priorities or {}
    ids = {k.id for k in kps}
    indeg = {i: 0 for i in ids}
    children = defaultdict(list)
    for r in relations:
        if r.from_kp_id in ids and r.to_kp_id in ids and r.approved:
            children[r.from_kp_id].append(r.to_kp_id)
            indeg[r.to_kp_id] += 1
    q = [(-priorities.get(i, 0.0), i) for i, d in indeg.items() if d == 0]
    heapq.heapify(q)
    out = []
    while q:
        _, u = heapq.heappop(q); out.append(u)
        for v in children[u]:
            indeg[v] -= 1
            if indeg[v] == 0: heapq.heappush(q, (-priorities.get(v, 0.0), v))
    return out if len(out) == len(ids) else sorted(ids)


def effective_minutes(mastery: float, exam_w: float, estimated_minutes: int) -> int:
    """动态复习时长：掌握度越高越短（0.7～1.3 倍），考纲分值越高越长（0.9～1.1 倍）。"""
    mastery_factor = 1.3 - 0.6 * mastery
    syllabus_factor = 0.9 + 0.2 * exam_w
    return max(10, round(estimated_minutes * mastery_factor * syllabus_factor))


def _allocate_compressed(scored: list, available: int) -> dict:
    """预算不足时压缩各知识点时长：保底 floor 分钟保证全覆盖，
    剩余预算按「考纲分值 × 掌握缺口」权重分配，使考试得分最大化。"""
    floor = 10
    n = len(scored)
    weights = [(kp.id, w) for kp, _p, _d, _m, w, _r in scored]
    total_w = sum(w for _, w in weights) or 1.0
    base = floor if n * floor <= available else (1 if n <= available else 0)
    alloc = {kp_id: base for kp_id, _w in weights} if base else {}
    budget = available - n * base
    shares = [budget * w / total_w for _, w in weights]
    low = [int(math.floor(s)) for s in shares]
    order = sorted(range(n), key=lambda i: shares[i] - low[i], reverse=True)
    for j in range(budget - sum(low)):
        low[order[j % n]] += 1
    for (kp_id, _w), extra in zip(weights, low):
        alloc[kp_id] = alloc.get(kp_id, 0) + extra
    return alloc


def ideal_total_minutes(db: Session, course_id: int, student_id: int) -> int:
    """未压缩的理想复习总时长，用于判断「预算是否充足」。"""
    kps = db.scalars(select(KnowledgePoint).where(
        KnowledgePoint.course_id == course_id, KnowledgePoint.approved == True  # noqa: E712
    )).all()
    reqs = {r.kp_id: r for r in db.scalars(select(CourseRequirement).where(
        CourseRequirement.course_id == course_id
    )).all()}
    states = {s.kp_id: s for s in db.scalars(select(StudentState).where(
        StudentState.student_id == student_id
    )).all()}
    total = 0
    for kp in kps:
        req = reqs.get(kp.id)
        if req and not req.included_in_exam:
            continue
        state = states.get(kp.id)
        mastery = state.mastery if state else 0.25
        exam_w = req.exam_weight if req else 0.5
        total += effective_minutes(mastery, exam_w, kp.estimated_minutes)
    return total


def generate_plan(db: Session, course_id: int, student_id: int, exam_date: str, daily_minutes: int):
    exam = date.fromisoformat(exam_date)
    days = max(1, (exam - date.today()).days + 1)
    daily_minutes = max(15, min(720, daily_minutes))
    available = days * daily_minutes
    kps = db.scalars(select(KnowledgePoint).where(
        KnowledgePoint.course_id == course_id, KnowledgePoint.approved == True  # noqa: E712
    )).all()
    reqs = {r.kp_id: r for r in db.scalars(select(CourseRequirement).where(
        CourseRequirement.course_id == course_id
    )).all()}
    states = {s.kp_id: s for s in db.scalars(select(StudentState).where(
        StudentState.student_id == student_id
    )).all()}
    relations = db.scalars(select(KnowledgeRelation).where(
        KnowledgeRelation.course_id == course_id
    )).all()
    scored = []
    for kp in kps:
        req = reqs.get(kp.id)
        if req and not req.included_in_exam:
            continue
        state = states.get(kp.id)
        mastery = state.mastery if state else 0.25
        forget = 1.0 - retention(state)
        exam_w = req.exam_weight if req else 0.5
        # 计划原则：考纲 50% · 掌握状态 30% · 遗忘风险 20%
        priority = 0.50 * exam_w + 0.30 * (1.0 - mastery) + 0.20 * forget
        reason = f"考纲{exam_w:.0%} · 掌握缺口{(1.0 - mastery):.0%} · 遗忘风险{forget:.0%}"
        # 每日安排标准：考试分值密度（考纲分值 ÷ 预计时长），
        # 让有限的剩余复习时间优先覆盖更多、更重要的知识点。
        score_density = exam_w / max(10, kp.estimated_minutes)
        # 压缩权重：考纲分值越高、掌握度越低，压缩时越应保留时间（期望得分提升）。
        weight = max(0.05, exam_w) * (1.0 - mastery) + 0.01
        scored.append((kp, priority, score_density,
                       effective_minutes(mastery, exam_w, kp.estimated_minutes), weight, reason))
    # 拓扑排序按考试分值密度优先，前置知识点仍先于依赖出现。
    density = {kp.id: d for kp, _, d, _m, _w, _ in scored}
    order = {kp_id: i for i, kp_id in enumerate(topological_order(kps, relations, density))}
    scored.sort(key=lambda x: order.get(x[0].id, 999999))

    old = db.scalars(select(StudyPlan).where(
        StudyPlan.course_id == course_id, StudyPlan.student_id == student_id
    )).all()
    for plan in old:
        db.execute(delete(PlanItem).where(PlanItem.plan_id == plan.id))
        db.delete(plan)
    db.flush()
    plan = StudyPlan(course_id=course_id, student_id=student_id, exam_date=exam_date, daily_minutes=daily_minutes)
    db.add(plan); db.flush()

    # 时间不足时压缩各知识点时长并均匀分布到每日，避免剩余任务堆积在最后一天。
    ideal_total = sum(m for _, _, _, m, _w, _ in scored)
    alloc = _allocate_compressed(scored, available) if ideal_total > available else None

    day, used = 1, 0
    for kp, priority, _density, minutes, _weight, reason in scored:
        remaining = alloc[kp.id] if alloc is not None else minutes
        while remaining > 0:
            room = daily_minutes - used
            if room <= 0:
                day += 1; used = 0
                continue
            chunk = min(remaining, room)
            db.add(PlanItem(plan_id=plan.id, kp_id=kp.id, day_index=day,
                            minutes=chunk, priority=priority, reason=reason))
            remaining -= chunk; used += chunk
            if used >= daily_minutes:
                day += 1; used = 0
    db.commit()
    return plan


def update_mastery(state: StudentState, correct: bool):
    now = utcnow()
    current = state.mastery * retention(state, now)
    if correct:
        state.mastery = min(0.995, current + 0.28 * (1.0 - current))
        state.stability = min(120.0, max(1.0, state.stability * 1.55 + 0.5))
        state.quiz_correct += 1
    else:
        state.mastery = max(0.02, current * 0.72)
        state.stability = max(0.5, state.stability * 0.65)
    state.quiz_total += 1
    state.review_count += 1
    state.last_reviewed_at = now
    state.updated_at = now


def update_familiarity(state: StudentState, familiar: bool):
    """Calibrate mastery from a self-report without treating it as a graded answer."""
    now = utcnow()
    current = state.mastery * retention(state, now)
    if familiar:
        state.mastery = min(0.95, current + 0.16 * (1.0 - current))
        state.stability = min(90.0, max(1.0, state.stability * 1.18 + 0.25))
        state.quiz_correct += 1
    else:
        state.mastery = max(0.02, current * 0.70)
        state.stability = max(0.5, state.stability * 0.78)
    state.quiz_total += 1
    state.review_count += 1
    state.last_reviewed_at = now
    state.updated_at = now
