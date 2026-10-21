from __future__ import annotations

import json
import os
import re
from typing import Any

import httpx


class LLMClient:
    """OpenAI-compatible provider adapter with a deterministic local fallback."""

    def __init__(self):
        self.api_key = os.getenv("LLM_API_KEY", "").strip()
        self.base_url = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        self.model = os.getenv("LLM_MODEL", "gpt-4.1-mini")

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def json_completion(self, system: str, user: str, fallback: Any) -> Any:
        if not self.configured:
            return fallback
        payload = {
            "model": self.model,
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        try:
            with httpx.Client(timeout=120) as client:
                r = client.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=payload,
                )
                r.raise_for_status()
                content = r.json()["choices"][0]["message"]["content"]
                content = re.sub(r"^```(?:json)?|```$", "", content.strip(), flags=re.M).strip()
                return json.loads(content)
        except Exception:
            return fallback


llm = LLMClient()
