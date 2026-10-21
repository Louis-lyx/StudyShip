"""Mine one atomic true/false proposition from every mirrored source exercise."""
from __future__ import annotations

import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
ENV = ROOT / ".env"
OUTPUT = ROOT / "vendor" / "judgment_questions_zh.json"


def load_env() -> None:
    if not ENV.is_file():
        return
    for line in ENV.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def clean_payload(row: dict) -> dict:
    return {
        "id": f"{row['source_code']}:{row['source_ref']}",
        "group": row["source_group"],
        "question": row["question_text"][:1600],
        "answer": row["answer_text"][:800],
        "explanation": row["explanation"][:1800],
    }


def mine_batch(client, index: int, batch: list[dict]) -> tuple[int, list[dict], set[str]]:
    payload = [clean_payload(row) for row in batch]
    result = client.json_completion(
        "你是数据结构课程题库编辑。你的任务是从已有成熟题目及答案中提炼原子知识，"
        "而不是凭空编题。严格依据输入，只输出JSON。",
        "逐题处理以下材料，每道原题输出一道中文判断题。要求：\n"
        "1. 挖掘原题背后的一个基础、独立、可判定的知识点，写成自包含陈述句；\n"
        "2. 约一半命题为正确、一半为错误。错误命题只替换一个关键事实（复杂度、定义、"
        "条件、算法性质或数据结构特征），保持迷惑性和教学价值；\n"
        "3. 题干不得提及原题、选项、答案或“是否熟悉”，长度尽量控制在100个汉字；\n"
        "4. explanation用1至2句解释判定依据；concept为最小知识点名称；\n"
        "5. 公式、变量和代码含义保持准确；信息不足时从解释文本中选择确定事实；\n"
        "6. id原样返回，correct必须为JSON布尔值。\n"
        "返回：{\"items\":[{\"id\":\"...\",\"statement\":\"...\","
        "\"correct\":true,\"explanation\":\"...\",\"concept\":\"...\"}]}\n"
        + json.dumps(payload, ensure_ascii=False),
        {"items": []},
    )
    return index, result.get("items", []) if isinstance(result, dict) else [], {x["id"] for x in payload}


def main() -> None:
    load_env()
    from app.services.external_questions import parse_opendsa, parse_yanweimin
    from app.services.llm import LLMClient

    client = LLMClient()
    if not client.configured:
        print("LLM_API_KEY is empty")
        return
    cached = json.loads(OUTPUT.read_text(encoding="utf-8")) if OUTPUT.is_file() else {}
    all_rows = parse_opendsa() + parse_yanweimin()
    rows = [row for row in all_rows if f"{row['source_code']}:{row['source_ref']}" not in cached]
    print(f"pending judgments: {len(rows)} / {len(all_rows)}", flush=True)
    batches = [rows[offset:offset + 16] for offset in range(0, len(rows), 16)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(mine_batch, client, index, batch)
                   for index, batch in enumerate(batches, 1)]
        for future in as_completed(futures):
            index, items, wanted = future.result()
            batch = batches[index - 1]
            accepted = 0
            for item in items:
                item_id = str(item.get("id", ""))
                statement = str(item.get("statement", "")).strip().rstrip("？?")
                explanation = str(item.get("explanation", "")).strip()
                concept = str(item.get("concept", "")).strip()
                correct = item.get("correct")
                if item_id in wanted and len(statement) >= 4 and isinstance(correct, bool):
                    cached[item_id] = {
                        "statement": statement,
                        "correct": correct,
                        "explanation": explanation,
                        "concept": concept,
                    }
                    accepted += 1
            OUTPUT.write_text(json.dumps(cached, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"batch {index}: {accepted}/{len(batch)}; cached={len(cached)}", flush=True)


if __name__ == "__main__":
    main()
