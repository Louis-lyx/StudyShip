"""Translate mirrored OpenDSA question stems once and cache the reviewed source text."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
ENV = ROOT / ".env"
OUTPUT = ROOT / "vendor" / "opendsa_question_zh.json"


def load_env() -> None:
    if not ENV.is_file():
        return
    for line in ENV.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def main() -> None:
    load_env()
    from app.services.external_questions import parse_opendsa
    from app.services.llm import LLMClient

    client = LLMClient()
    if not client.configured:
        print("LLM_API_KEY is empty")
        return
    cached = json.loads(OUTPUT.read_text(encoding="utf-8")) if OUTPUT.is_file() else {}
    rows = [x for x in parse_opendsa() if x["source_ref"] not in cached]
    print(f"pending translations: {len(rows)}")
    for offset in range(0, len(rows), 24):
        batch = rows[offset:offset + 24]
        payload = [{"id": x["source_ref"], "text": x["question_text"]} for x in batch]
        fallback = {"translations": []}
        result = client.json_completion(
            "你是数据结构课程翻译员，只翻译原题，不增删考点，只输出JSON。",
            "把以下英文数据结构题干准确翻译为简体中文，保留公式、变量、代码和专有名词。"
            "返回结构：{\"translations\":[{\"id\":\"原id\",\"text\":\"中文题干\"}]}。\n"
            + json.dumps(payload, ensure_ascii=False),
            fallback,
        )
        accepted = 0
        for item in result.get("translations", []) if isinstance(result, dict) else []:
            source_ref = str(item.get("id", ""))
            text = str(item.get("text", "")).strip()
            if source_ref in {x["source_ref"] for x in batch} and len(text) >= 3:
                cached[source_ref] = text
                accepted += 1
        OUTPUT.write_text(json.dumps(cached, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"batch {offset // 24 + 1}: {accepted}/{len(batch)}; cached={len(cached)}")


if __name__ == "__main__":
    main()
