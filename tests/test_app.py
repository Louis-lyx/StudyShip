from datetime import date, timedelta
import fitz
import pytest
import os
import tempfile
from pathlib import Path

_TEST_ROOT = Path(tempfile.mkdtemp(prefix="studyship-tests-"))
os.environ["STUDYSHIP_DB_PATH"] = str(_TEST_ROOT / "test.db")
os.environ["STUDYSHIP_UPLOAD_DIR"] = str(_TEST_ROOT / "uploads")

from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.main import PARSE_PROGRESS, ParseCancelled, app, parse_progress_callback, update_parse_progress
from app.services.documents import infer_toc


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def login(client, username):
    r = client.post("/api/auth/login", json={"username": username, "password": "StudyShip@2026"})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["ok"] is True


def test_teacher_manages_multiple_courses_and_selects_base_library(client):
    teacher = login(client, "demo_teacher")
    first = client.post("/api/courses", headers=teacher, json={
        "name": "操作系统", "code": "", "academic_year": "2026-2027",
        "description": "多课程测试一",
    })
    assert first.status_code == 200
    first_course = first.json()
    assert first_course["code"].startswith("COURSE-")

    second = client.post("/api/courses", headers=teacher, json={
        "name": "计算机网络", "code": "MULTI-NET", "academic_year": "2026-2027",
        "description": "多课程测试二",
    })
    assert second.status_code == 200
    second_course = second.json()

    renamed = client.patch(f"/api/courses/{first_course['id']}", headers=teacher, json={
        "name": "操作系统原理", "description": "已修改课程名称",
    })
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "操作系统原理"

    duplicate = client.patch(f"/api/courses/{first_course['id']}", headers=teacher,
                             json={"code": second_course["code"]})
    assert duplicate.status_code == 409

    templates = client.get("/api/curriculum-templates", headers=teacher).json()
    assert templates
    applied = client.post(
        f"/api/courses/{first_course['id']}/curriculum-template"
        f"?template_code={templates[0]['code']}", headers=teacher,
    )
    assert applied.status_code == 200
    outline = client.post(f"/api/courses/{first_course['id']}/outlines", headers=teacher,
                          data={"title": "操作系统测试目录",
                                "outline_text": "第1章 绪论\n1.1 算法和算法分析"})
    assert outline.status_code == 200

    courses = client.get("/api/courses", headers=teacher).json()
    one = next(x for x in courses if x["id"] == first_course["id"])
    two = next(x for x in courses if x["id"] == second_course["id"])
    assert one["name"] == "操作系统原理" and one["template_code"] == templates[0]["code"]
    assert one["knowledge_points"] > 0 and two["knowledge_points"] == 0

    script = client.get("/assets/app.js").text
    assert "template-select" in script and "courseStorageKey" in script
    assert "data-course-edit" in script and "data-course-open" in script


def test_teacher_can_cancel_parse(client):
    teacher = login(client, "demo_teacher")
    course = client.get("/api/courses", headers=teacher).json()[0]
    job_id = "cancel-test-job"
    update_parse_progress(job_id, status="parsing", stage="测试解析", course_id=course["id"],
                          completed_sections=1, total_sections=4)
    r = client.post(f"/api/parse-progress/{job_id}/cancel", headers=teacher)
    assert r.status_code == 200 and r.json()["status"] == "cancelling"
    with pytest.raises(ParseCancelled):
        parse_progress_callback(job_id)(stage="下一章节")
    PARSE_PROGRESS.pop(job_id, None)


def test_toc_inference_filters_front_matter_noise():
    pages = [
        "010-62782989 13701121933\nISBN 978-7-302-14751-0\nhttp://www.example.com\n",
        "1.1 线性表的定义\n正文内容\n2.3 图的遍历\n",
    ]
    toc = infer_toc(pages)
    titles = [x[1] for x in toc]
    assert "1.1 线性表的定义" in titles and "2.3 图的遍历" in titles
    assert not any("62782989" in x or "ISBN" in x or "http" in x for x in titles)


def test_pasted_long_toc_scans_all_lines_and_removes_printed_pages():
    lines = ["目录"]
    for chapter in range(1, 13):
        lines.append(f"第{chapter}章 测试章节{chapter} {chapter * 20}")
        for section in range(1, 4):
            marker = "**" if chapter == 3 and section == 3 else ""
            lines.append(f"{marker}{chapter}.{section} 测试小节{chapter}-{section} {chapter * 20 + section}")
    toc = infer_toc(["\n".join(lines)])
    titles = [item[1] for item in toc]
    assert len(toc) == 48
    assert "第12章 测试章节12" in titles
    assert "3.3 测试小节3-3" in titles
    assert not any(title.endswith(" 240") for title in titles)


def test_demo_auth_and_courses(client):
    teacher = login(client, "demo_teacher")
    student = login(client, "demo_student")
    tc = client.get("/api/courses", headers=teacher).json()
    sc = client.get("/api/courses", headers=student).json()
    assert tc and sc and tc[0]["code"] == "DS-DEMO"


def test_local_outline_drives_course_and_opendsa_supplies_theory(client):
    teacher = login(client, "demo_teacher")
    code = "DS-OUTLINE-OVERLAY"
    existing = [c for c in client.get("/api/courses", headers=teacher).json() if c["code"] == code]
    if existing:
        course_id = existing[0]["id"]
    else:
        r = client.post("/api/courses", headers=teacher, json={
            "name": "目录映射测试", "code": code, "description": "基准框架覆盖层",
            "academic_year": "2026-2027",
        })
        assert r.status_code == 200
        course_id = r.json()["id"]
    r = client.post(f"/api/courses/{course_id}/curriculum-template", headers=teacher)
    assert r.status_code == 200
    review = client.get(f"/api/courses/{course_id}/outline-review", headers=teacher).json()
    assert review["template"]["name"] == "数据结构细粒度理论资源库"
    assert review["chapters"] == []
    assert review["template"]["resource_points"] >= 100
    assert review["template"]["theory_modules"] >= 70
    before = client.get(f"/api/courses/{course_id}/knowledge", headers=teacher).json()
    assert before["knowledge_points"] == []
    outline_text = """第一章 绪论与算法分析
1.1 数据结构基本概念
1.2 算法与复杂度
第二章 线性表
2.1 顺序表
2.2 链表
第三章 栈和队列
3.1 栈
3.2 队列
第六章 图
6.1 图的存储
6.2 图的遍历
第八章 排序
8.1 基础排序
8.2 高效排序"""
    r = client.post(f"/api/courses/{course_id}/outlines", headers=teacher,
                    data={"title": "测试教材目录", "outline_text": outline_text})
    assert r.status_code == 200 and r.json()["matched"] >= 10
    after = client.get(f"/api/courses/{course_id}/knowledge", headers=teacher).json()
    assert len(after["knowledge_points"]) >= 20
    assert not any(point["name"] == "KMP模式匹配" for point in after["knowledge_points"])
    review = client.get(f"/api/courses/{course_id}/outline-review", headers=teacher).json()
    assert [chapter["title"] for chapter in review["chapters"]] == [
        "第一章 绪论与算法分析", "第二章 线性表", "第三章 栈和队列",
        "第六章 图", "第八章 排序",
    ]
    points = [p for c in review["chapters"] for s in c["sections"] for p in s["points"]]
    assert points and all(p["coverage_status"] == "course" for p in points)
    theory_point = next(p for p in points if p["theory_modules"] > 0)
    theory = client.get(f"/api/knowledge/{theory_point['id']}/theory", headers=teacher)
    assert theory.status_code == 200 and theory.json()["modules"]
    first_chapter = review["chapters"][0]
    r = client.post(f"/api/topics/{first_chapter['topic_id']}/approve", headers=teacher)
    assert r.status_code == 200 and r.json()["knowledge_points"] > 0


def test_fine_grained_pool_covers_memory_external_sort_and_files(client):
    teacher = login(client, "demo_teacher")
    r = client.post("/api/courses", headers=teacher, json={
        "name": "细粒度资源测试", "code": "DS-FINE-POOL",
        "description": "覆盖教材后半部分", "academic_year": "2026-2027",
    })
    assert r.status_code == 200
    course_id = r.json()["id"]
    assert client.post(f"/api/courses/{course_id}/curriculum-template", headers=teacher).status_code == 200
    outline = """第8章 动态存储管理 193
8.5 无用单元收集 206
第11章 外部排序 293
11.3 多路平衡归并的实现 297
第12章 文件 306
12.4.1 ISAM文件 313"""
    r = client.post(f"/api/courses/{course_id}/outlines", headers=teacher,
                    data={"title": "教材后半部分", "outline_text": outline})
    assert r.status_code == 200 and r.json()["matched"] >= 5
    graph = client.get(f"/api/courses/{course_id}/knowledge", headers=teacher).json()
    names = {point["name"] for point in graph["knowledge_points"]}
    assert {"无用单元收集", "多路平衡归并", "ISAM文件"}.issubset(names)
    memory = next(point for point in graph["knowledge_points"] if point["name"] == "无用单元收集")
    theory = client.get(f"/api/knowledge/{memory['id']}/theory", headers=teacher).json()
    assert theory["modules"]


def test_knowledge_graph(client):
    teacher = login(client, "demo_teacher")
    course = client.get("/api/courses", headers=teacher).json()[0]
    data = client.get(f"/api/courses/{course['id']}/knowledge", headers=teacher).json()
    assert len(data["knowledge_points"]) >= 8
    assert len(data["relations"]) >= 7
    assert all(k["approved"] for k in data["knowledge_points"])


def test_relation_cycle_is_rejected(client):
    teacher = login(client, "demo_teacher")
    course = next(c for c in client.get("/api/courses", headers=teacher).json() if c["code"] == "DS-DEMO")
    data = client.get(f"/api/courses/{course['id']}/knowledge", headers=teacher).json()
    by_name = {k["name"]: k["id"] for k in data["knowledge_points"]}
    r = client.post(f"/api/courses/{course['id']}/relations", headers=teacher, json={
        "from_kp_id": by_name["最短路径"], "to_kp_id": by_name["图的存储"],
        "relation_type": "prerequisite", "approved": True,
    })
    assert r.status_code == 409


def test_student_states_plan_and_quiz(client):
    student = login(client, "demo_student")
    course = client.get("/api/courses", headers=student).json()[0]
    states = client.get(f"/api/courses/{course['id']}/states", headers=student).json()
    assert states
    first = states[0]
    r = client.put(f"/api/states/{first['kp_id']}", headers=student, json={"mastery": 0.33})
    assert r.status_code == 200
    exam = (date.today() + timedelta(days=20)).isoformat()
    r = client.post(f"/api/courses/{course['id']}/plans", headers=student,
                    json={"exam_date": exam, "daily_minutes": 90})
    assert r.status_code == 200 and r.json()["items"]
    plan = r.json()
    graph = client.get(f"/api/courses/{course['id']}/knowledge", headers=student).json()
    first_position = {}
    for i, item in enumerate(plan["items"]):
        first_position.setdefault(item["kp_id"], i)
    for rel in graph["relations"]:
        if rel["approved"] and rel["from"] in first_position and rel["to"] in first_position:
            assert first_position[rel["from"]] < first_position[rel["to"]]
    q = client.get(f"/api/courses/{course['id']}/quiz", headers=student).json()[0]
    assert q["response_mode"] == "judgment"
    assert q["statement"] and q["question_id"]
    r = client.post("/api/quiz/submit", headers=student, json={
        "question_id": q["question_id"], "kp_id": q["kp_id"],
        "question": q["statement"], "answer": "正确", "judgment": True,
    })
    assert r.status_code == 200 and isinstance(r.json()["correct"], bool)

    # A deliberately tiny time budget reports overload but keeps every topic.
    r = client.post(f"/api/courses/{course['id']}/plans", headers=student,
                    json={"exam_date": date.today().isoformat(), "daily_minutes": 15})
    overloaded = r.json()
    assert r.status_code == 200 and overloaded["overloaded"] is True
    assert len({x["kp_id"] for x in overloaded["items"]}) == len(graph["knowledge_points"])
    # zhc policy compresses the actual allocation into the available budget and
    # distributes it within the valid day range instead of piling overflow onto the last day.
    assert sum(x["minutes"] for x in overloaded["items"]) <= overloaded["capacity_minutes"]
    assert max(x["day"] for x in overloaded["items"]) <= overloaded["days"]


def test_teacher_builds_chapter_focused_judgment_bank(client):
    teacher = login(client, "demo_teacher")
    course = client.get("/api/courses", headers=teacher).json()[0]
    r = client.post(f"/api/courses/{course['id']}/question-bank/generate", headers=teacher)
    assert r.status_code == 200
    result = r.json()
    assert result["count"] > 700 and result["chapters"] > 0
    assert result["source_counts"]["opendsa"] > 400
    assert result["source_counts"]["yanweimin"] > 300

    bank = client.get(f"/api/courses/{course['id']}/question-bank", headers=teacher).json()
    assert bank["count"] == result["count"]
    assert all(q["statement"] and q["chapter"] for q in bank["questions"])
    assert all(isinstance(q["correct_answer"], bool) for q in bank["questions"])
    assert all(0 < q["focus_score"] <= 1 for q in bank["questions"])
    assert set(bank["source_counts"]) == {"opendsa", "yanweimin"}

    student = login(client, "demo_student")
    q = client.get(f"/api/courses/{course['id']}/quiz?count=1", headers=student).json()[0]
    assert q["source"] in {"opendsa", "yanweimin"}
    answer = next(x["correct_answer"] for x in bank["questions"] if x["id"] == q["question_id"])
    before = next(x for x in client.get(
        f"/api/courses/{course['id']}/states", headers=student).json() if x["kp_id"] == q["kp_id"])
    r = client.post("/api/quiz/submit", headers=student, json={
        "question_id": q["question_id"], "kp_id": q["kp_id"],
        "question": q["statement"], "judgment": not answer,
    })
    assert r.status_code == 200 and r.json()["correct"] is False
    assert r.json()["mastery"] < before["mastery"]


def test_create_course_and_parse_textbook(client, tmp_path):
    teacher = login(client, "demo_teacher")
    code = "TEST-PDF-COURSE"
    existing = [c for c in client.get("/api/courses", headers=teacher).json() if c["code"] == code]
    if existing:
        course = existing[0]
    else:
        r = client.post("/api/courses", headers=teacher, json={
            "name": "PDF解析测试课程", "code": code, "description": "自动测试", "academic_year": "2026-2027",
        })
        assert r.status_code == 200
        course = next(c for c in client.get("/api/courses", headers=teacher).json() if c["id"] == r.json()["id"])
    text = """第一章 算法基础\n1.1 时间复杂度\n时间复杂度用于描述算法运行时间随输入规模的增长。\n1.2 空间复杂度\n空间复杂度描述额外存储空间。\n第二章 线性表\n2.1 顺序表\n顺序表使用连续存储空间。\n2.2 链表\n链表通过指针连接节点。"""
    path = tmp_path / "book.txt"; path.write_text(text, encoding="utf-8")
    with path.open("rb") as f:
        r = client.post(f"/api/courses/{course['id']}/books", headers=teacher,
                        data={"title": "测试教材", "author": "测试作者"},
                        files={"file": ("book.txt", f, "text/plain")})
    assert r.status_code == 200
    assert r.json().get("knowledge_points", 0) >= 2 or r.json().get("duplicate")
    progress = client.get(f"/api/parse-progress/{r.json()['job_id']}", headers=teacher)
    assert progress.status_code == 200 and progress.json()["progress_percent"] == 100
    assert progress.json()["remaining_seconds"] == 0
    r = client.post(f"/api/courses/{course['id']}/knowledge/approve-all", headers=teacher)
    assert r.status_code == 200
    books = client.get(f"/api/courses/{course['id']}/books", headers=teacher).json()
    assert books[0]["status"] == "ready"
    r = client.post(f"/api/courses/{course['id']}/publish", headers=teacher)
    assert r.status_code == 200


def test_parse_real_pdf(client, tmp_path):
    teacher = login(client, "demo_teacher")
    code = "TEST-REAL-PDF"
    r = client.post("/api/courses", headers=teacher, json={
        "name": "真实PDF解析测试", "code": code, "description": "PDF书签解析", "academic_year": "2026-2027",
    })
    assert r.status_code == 200
    course_id = r.json()["id"]
    pdf_path = tmp_path / "algorithm.pdf"
    doc = fitz.open()
    page1 = doc.new_page()
    page1.insert_text((72, 72), "1 Algorithm Foundations\n1.1 Time Complexity\nComplexity describes growth with input size.")
    page2 = doc.new_page()
    page2.insert_text((72, 72), "2 Linear Structures\n2.1 Linked List\nNodes are connected with links.")
    doc.set_toc([[1, "Algorithm Foundations", 1], [2, "Time Complexity", 1],
                 [1, "Linear Structures", 2], [2, "Linked List", 2]])
    doc.save(pdf_path)
    doc.close()
    with pdf_path.open("rb") as f:
        r = client.post(f"/api/courses/{course_id}/books", headers=teacher,
                        data={"title": "Algorithm Book", "author": "Test"},
                        files={"file": ("algorithm.pdf", f, "application/pdf")})
    assert r.status_code == 200
    book_id = r.json()["id"]
    assert r.json()["topics"] == 4
    assert r.json()["knowledge_points"] >= 2
    r = client.post(f"/api/books/{book_id}/retry", headers=teacher)
    assert r.status_code == 200 and r.json()["knowledge_points"] >= 2
    graph = client.get(f"/api/courses/{course_id}/knowledge", headers=teacher).json()
    assert any(t["title"] == "Time Complexity" for t in graph["topics"])
    count_before = len(graph["knowledge_points"])
    r = client.delete(f"/api/knowledge/{graph['knowledge_points'][0]['id']}", headers=teacher)
    assert r.status_code == 200
    graph = client.get(f"/api/courses/{course_id}/knowledge", headers=teacher).json()
    assert len(graph["knowledge_points"]) == count_before - 1
    student = login(client, "demo_student")
    assert client.delete(f"/api/books/{book_id}", headers=student).status_code == 403
    r = client.delete(f"/api/books/{book_id}", headers=teacher)
    assert r.status_code == 200 and r.json()["removed_knowledge_points"] == count_before - 1
    assert client.get(f"/api/courses/{course_id}/books", headers=teacher).json() == []
    assert client.get(f"/api/courses/{course_id}/knowledge", headers=teacher).json()["knowledge_points"] == []


def test_resource_evidence_flow(client, tmp_path):
    teacher = login(client, "demo_teacher")
    course = next(c for c in client.get("/api/courses", headers=teacher).json() if c["code"] == "DS-DEMO")
    path = tmp_path / "syllabus.txt"
    path.write_text("考试重点：熟练掌握图的存储、图的遍历和最短路径。", encoding="utf-8")
    with path.open("rb") as f:
        r = client.post(f"/api/courses/{course['id']}/resources", headers=teacher,
                        data={"title": "测试考纲", "resource_type": "syllabus"},
                        files={"file": ("syllabus.txt", f, "text/plain")})
    assert r.status_code == 200 and r.json()["evidence_count"] >= 2
    evidence = client.get(f"/api/courses/{course['id']}/evidence?status=pending", headers=teacher).json()
    assert evidence
    r = client.post(f"/api/evidence/{evidence[0]['id']}/review?approve=true", headers=teacher)
    assert r.status_code == 200
    r = client.post(f"/api/courses/{course['id']}/evidence/review-all?approve=true", headers=teacher)
    assert r.status_code == 200
    assert client.get(f"/api/courses/{course['id']}/evidence?status=pending", headers=teacher).json() == []


def test_personal_learning_resources_are_private_and_keep_framework_fixed(client, tmp_path):
    teacher = login(client, "demo_teacher")
    student = login(client, "demo_student")
    course = next(c for c in client.get("/api/courses", headers=teacher).json() if c["code"] == "DS-DEMO")
    graph_before = client.get(f"/api/courses/{course['id']}/knowledge", headers=teacher).json()
    framework_before = (
        len(graph_before["topics"]), len(graph_before["knowledge_points"]), len(graph_before["relations"]),
    )
    names = [point["name"] for point in graph_before["knowledge_points"][:2]]
    assert names
    path = tmp_path / "personal-notes.txt"
    path.write_text("我的复习笔记：" + "、".join(names) + "。需要理解定义、基本操作和复杂度。", encoding="utf-8")
    with path.open("rb") as f:
        uploaded = client.post(
            f"/api/courses/{course['id']}/resources", headers=student,
            data={"title": "我的链表笔记", "resource_type": "self_study"},
            files={"file": ("personal-notes.txt", f, "text/plain")},
        )
    assert uploaded.status_code == 200
    assert uploaded.json()["audience"] == "personal" and uploaded.json()["evidence_count"] >= 1

    mine = client.get(f"/api/courses/{course['id']}/resources", headers=student).json()
    assert any(row["id"] == uploaded.json()["id"] for row in mine)
    mappings = client.get(f"/api/courses/{course['id']}/personal-evidence", headers=student).json()
    assert mappings and all(row["concept_name"] and row["kp_name"] for row in mappings)
    student_theory = client.get(f"/api/knowledge/{mappings[0]['kp_id']}/theory", headers=student).json()
    assert any(row["resource"] == "我的链表笔记" and row["scope"] == "personal"
               for row in student_theory["material_concepts"])

    teacher_resources = client.get(f"/api/courses/{course['id']}/resources", headers=teacher).json()
    assert all(row["id"] != uploaded.json()["id"] for row in teacher_resources)
    teacher_theory = client.get(f"/api/knowledge/{mappings[0]['kp_id']}/theory", headers=teacher).json()
    assert all(row["resource"] != "我的链表笔记" for row in teacher_theory["material_concepts"])
    teacher_evidence = client.get(f"/api/courses/{course['id']}/evidence?status=all", headers=teacher).json()
    assert all(row["id"] not in {item["id"] for item in mappings} for row in teacher_evidence)

    username = "private_material_student"
    registered = client.post("/api/auth/register", json={
        "username": username, "password": "StudyShip@2026", "display_name": "隔离测试学生",
        "role": "student", "student_no": "PRIVATE-001",
    })
    if registered.status_code == 409:
        other = login(client, username)
    else:
        assert registered.status_code == 200
        other = {"Authorization": f"Bearer {registered.json()['token']}"}
    client.post(f"/api/courses/{course['id']}/enroll", headers=other)
    assert client.get(f"/api/courses/{course['id']}/resources", headers=other).json() == []
    assert client.get(f"/api/courses/{course['id']}/personal-evidence", headers=other).json() == []
    other_theory = client.get(f"/api/knowledge/{mappings[0]['kp_id']}/theory", headers=other).json()
    assert all(row["resource"] != "我的链表笔记" for row in other_theory["material_concepts"])

    graph_after = client.get(f"/api/courses/{course['id']}/knowledge", headers=teacher).json()
    assert framework_before == (
        len(graph_after["topics"]), len(graph_after["knowledge_points"]), len(graph_after["relations"]),
    )
    removed = client.delete(f"/api/resources/{uploaded.json()['id']}", headers=student)
    assert removed.status_code == 200
    assert all(row["id"] != uploaded.json()["id"] for row in
               client.get(f"/api/courses/{course['id']}/resources", headers=student).json())


def test_static_app(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "StudyShip" in r.text
    script = client.get("/assets/app.js").text
    assert "自主学习资料上传" in script and "['resources','▤','教学资料']" in script
