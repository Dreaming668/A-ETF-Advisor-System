from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests


@dataclass
class ModelProviderProbe:
    name: str
    installed: bool
    usable: bool
    detail: str


class OpenAIResponsesProvider:
    name = "openai"

    def __init__(self, api_key: str, base_url: str, model: str, timeout: int = 45, max_retries: int = 2):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries

    def generate_text(
        self,
        developer_prompt: str,
        user_prompt: str,
        max_output_tokens: int = 900,
        reasoning_effort: str = "low",
    ) -> str:
        payload = {
            "model": self.model,
            "instructions": developer_prompt,
            "input": user_prompt,
            "reasoning": {"effort": reasoning_effort},
            "temperature": 0.2,
            "max_output_tokens": max_output_tokens,
        }
        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                response = requests.post(
                    f"{self.base_url}/responses",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=self.timeout,
                )
                if response.status_code == 429:
                    message = self._extract_error_message(response)
                    raise RuntimeError(f"OpenAI 429: {message}")
                response.raise_for_status()
                data = response.json()
                text = self._extract_output_text(data)
                if not text:
                    if data.get("status") == "incomplete":
                        reason = (data.get("incomplete_details") or {}).get("reason", "unknown")
                        raise RuntimeError(f"模型输出不完整: {reason}")
                    raise RuntimeError("模型未返回文本输出")
                return text
            except Exception as exc:
                last_error = exc
                if attempt < self.max_retries:
                    time.sleep(1.2 * (attempt + 1))
                else:
                    raise
        raise RuntimeError(str(last_error))

    def generate_json(
        self,
        developer_prompt: str,
        user_prompt: str,
        default: dict[str, Any],
        max_output_tokens: int = 1200,
        reasoning_effort: str = "low",
    ) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "instructions": developer_prompt,
            "input": (
                f"{user_prompt}\n\n"
                "请严格输出一个 JSON object，不要附带 markdown 代码块，不要输出 JSON 之外的解释。"
            ),
            "reasoning": {"effort": reasoning_effort},
            "temperature": 0.2,
            "max_output_tokens": max_output_tokens,
            "text": {"format": {"type": "json_object"}},
        }
        raw = self._request_text(payload)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            start = raw.find("{")
            end = raw.rfind("}")
            if start != -1 and end != -1 and end > start:
                try:
                    return json.loads(raw[start:end + 1])
                except json.JSONDecodeError:
                    pass
            return default

    def _request_text(self, payload: dict[str, Any]) -> str:
        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                request_timeout = max(30, int(self.timeout * (1 + attempt * 0.35)))
                response = requests.post(
                    f"{self.base_url}/responses",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=request_timeout,
                )
                if response.status_code == 429:
                    message = self._extract_error_message(response)
                    raise RuntimeError(f"OpenAI 429: {message}")
                response.raise_for_status()
                data = response.json()
                text = self._extract_output_text(data)
                if not text:
                    if data.get("status") == "incomplete":
                        reason = (data.get("incomplete_details") or {}).get("reason", "unknown")
                        raise RuntimeError(f"模型输出不完整: {reason}")
                    raise RuntimeError("模型未返回文本输出")
                return text
            except requests.Timeout as exc:
                last_error = RuntimeError(f"LLM 请求超时（{request_timeout}s）: {exc}")
                if attempt < self.max_retries:
                    time.sleep(1.5 * (attempt + 1))
                else:
                    raise last_error
            except Exception as exc:
                last_error = exc
                if attempt < self.max_retries:
                    time.sleep(1.2 * (attempt + 1))
                else:
                    raise
        raise RuntimeError(str(last_error))

    def verify(self) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "instructions": "You are a connectivity test assistant.",
            "input": "请只输出：OpenAI 连通成功",
            "reasoning": {"effort": "low"},
            "temperature": 0.0,
            "max_output_tokens": 1200,
        }
        response = requests.post(
            f"{self.base_url}/responses",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=self.timeout,
        )
        ok = response.status_code == 200
        detail = response.text[:500]
        return {"ok": ok, "status_code": response.status_code, "detail": detail}

    @staticmethod
    def _extract_output_text(data: dict[str, Any]) -> str:
        direct = data.get("output_text")
        if isinstance(direct, str) and direct.strip():
            return direct.strip()
        texts: list[str] = []
        for item in data.get("output", []):
            if item.get("type") != "message":
                continue
            for content in item.get("content", []):
                if content.get("type") == "output_text" and content.get("text"):
                    texts.append(content["text"])
        return "\n".join(texts).strip()

    @staticmethod
    def _extract_error_message(response: requests.Response) -> str:
        try:
            data = response.json()
            return data.get("error", {}).get("message", response.text[:300])
        except Exception:
            return response.text[:300]


def probe_openai() -> ModelProviderProbe:
    _load_env_file()
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return ModelProviderProbe(name="openai", installed=True, usable=False, detail="未设置 OPENAI_API_KEY")
    return ModelProviderProbe(name="openai", installed=True, usable=True, detail="已配置，待实际校验")


def provider_status() -> dict[str, Any]:
    openai_probe = probe_openai()
    return {
        "preferred": "openai" if openai_probe.usable else "openai_unavailable",
        "providers": [openai_probe.__dict__],
    }


def resolve_provider(preferred: str = "auto"):
    _load_env_file()
    openai_probe = probe_openai()
    if preferred == "openai":
        if not openai_probe.usable:
            raise RuntimeError(openai_probe.detail)
        return OpenAIResponsesProvider(
            api_key=os.getenv("OPENAI_API_KEY", "").strip(),
            base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").strip(),
            model=os.getenv("OPENAI_MODEL", "gpt-5-mini").strip(),
            timeout=int(os.getenv("OPENAI_TIMEOUT", "45")),
        )
    if openai_probe.usable:
        return OpenAIResponsesProvider(
            api_key=os.getenv("OPENAI_API_KEY", "").strip(),
            base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").strip(),
            model=os.getenv("OPENAI_MODEL", "gpt-5-mini").strip(),
            timeout=int(os.getenv("OPENAI_TIMEOUT", "45")),
        )
    raise RuntimeError(openai_probe.detail)


_ENV_LOADED = False


def _load_env_file() -> None:
    global _ENV_LOADED
    if _ENV_LOADED:
        return

    current = Path(__file__).resolve()
    env_paths = [current.parents[3] / ".env", current.parents[2] / ".env", Path.cwd() / ".env"]
    for env_path in env_paths:
        if not env_path.exists():
            continue
        try:
            for raw_line in env_path.read_text(encoding="utf-8-sig").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip("\"'")
                if key and key not in os.environ:
                    os.environ[key] = value
        except Exception:
            continue

    _ENV_LOADED = True
