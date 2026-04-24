from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

from .llm_provider import provider_status as llm_provider_status, resolve_provider


class AgentOrchestrator:
    def __init__(self, preferred_provider: str = "auto"):
        self.provider = resolve_provider(preferred_provider)
        self.status = llm_provider_status()
        if self.provider is None:
            raise RuntimeError("LLM provider unavailable. Please configure OPENAI_API_KEY and related settings.")

    def enrich_analysis(self, analysis: dict[str, Any]) -> dict[str, Any]:
        etf = analysis["etf"]
        latest = analysis["latest_quote"]
        factor = analysis["factor"]
        profile = analysis["risk_profile"]
        quotes = analysis["quotes"][-20:]
        news = analysis["news"][:5]
        constituents = analysis["constituents"][:10]

        empty_expert = {"summary": "", "signals": [], "risks": [], "confidence": 0.0}

        expert_tasks = {
            "market": (
                "市场专家",
                (
                    "你是A股ETF市场专家。你必须直接基于输入数据独立完成分析，不要引用任何已有观点，不要说信息不足，"
                    "不要输出模板化空话。输出 JSON：summary, signals, risks, confidence。"
                    "signals 和 risks 各输出 3 到 5 条，confidence 为 0 到 1 的数字。"
                    "summary 写成 120 到 180 字的完整分析，不要过度简写。"
                ),
                {
                    "etf": etf,
                    "latest_quote": latest,
                    "recent_quotes": quotes,
                    "risk_profile": profile,
                },
            ),
            "news": (
                "新闻分析师",
                (
                    "你是A股ETF新闻分析师。你必须直接基于新闻标题、摘要、来源和时间独立完成分析，"
                    "给出情绪、催化、持续性和风险。输出 JSON：summary, signals, risks, confidence。"
                    "signals 和 risks 各输出 3 到 5 条，confidence 为 0 到 1 的数字。"
                    "summary 写成 120 到 180 字的完整分析，不要过度简写。"
                ),
                {
                    "etf": etf,
                    "news": news,
                    "risk_profile": profile,
                },
            ),
            "alpha": (
                "Alpha分析师",
                (
                    "你是A股ETF Alpha分析师。你必须直接基于因子分数、量价表现和风格特征独立完成分析，"
                    "解释优势因子、拖累因子、拥挤度和风格适配。输出 JSON：summary, signals, risks, confidence。"
                    "signals 和 risks 各输出 3 到 5 条，confidence 为 0 到 1 的数字。"
                    "summary 写成 120 到 180 字的完整分析，不要过度简写。"
                ),
                {
                    "etf": etf,
                    "factor": factor,
                    "latest_quote": latest,
                    "recent_quotes": quotes,
                },
            ),
            "fundamental": (
                "基本面分析师",
                (
                    "你是A股ETF基本面分析师。你必须直接基于成分股权重、估值、盈利能力、成长性和行业分布独立完成分析。"
                    "输出 JSON：summary, signals, risks, confidence。signals 和 risks 各输出 3 到 5 条，"
                    "confidence 为 0 到 1 的数字。summary 写成 120 到 180 字的完整分析，不要过度简写。"
                ),
                {
                    "etf": etf,
                    "constituents": constituents,
                    "factor": factor,
                },
            ),
        }
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {
                key: executor.submit(self._run_expert, expert_name, prompt, context, empty_expert)
                for key, (expert_name, prompt, context) in expert_tasks.items()
            }
            market = futures["market"].result()
            news_view = futures["news"].result()
            alpha = futures["alpha"].result()
            fundamental = futures["fundamental"].result()
        general = self._run_expert(
            "通用专家",
            (
                "你是A股ETF投顾系统的通用专家。你必须直接综合市场、新闻、Alpha、基本面四位专家的结论，"
                "再结合用户风险画像，独立给出投资建议。输出 JSON：summary, signals, risks, confidence, recommendation。"
                "recommendation 仅能从 分批布局/继续持有/关注观察/控制仓位/小仓位关注 中选择。"
                "signals 和 risks 各输出 3 到 5 条，confidence 为 0 到 1 的数字。"
                "summary 写成 160 到 240 字的完整分析，明确结论、依据和执行思路，不要过度简写。"
            ),
            {
                "etf": etf,
                "risk_profile": profile,
                "latest_quote": latest,
                "market": market,
                "news": news_view,
                "alpha": alpha,
                "fundamental": fundamental,
            },
            {**empty_expert, "recommendation": "关注观察"},
        )

        analysis["experts"] = {
            "market": {**market, "name": "市场专家"},
            "news": {**news_view, "name": "新闻分析师"},
            "alpha": {**alpha, "name": "Alpha分析师"},
            "fundamental": {**fundamental, "name": "基本面分析师"},
            "general": {**general, "name": "通用专家"},
        }
        analysis["agent_mode"] = "llm"
        analysis.setdefault("sources", []).append({"name": f"LLM:{self.provider.model}", "type": "llm"})
        return analysis

    def _run_expert(self, expert_name: str, developer_prompt: str, context: dict[str, Any], default: dict[str, Any]) -> dict[str, Any]:
        user_prompt = f"专家角色: {expert_name}\n上下文数据:\n{context}"
        result = self.provider.generate_json(
            developer_prompt,
            user_prompt,
            default,
            max_output_tokens=1800 if expert_name != "通用专家" else 2400,
            reasoning_effort="low",
        )
        merged = self._normalize_expert_payload(result, default)
        if not merged.get("summary"):
            raise RuntimeError(f"{expert_name} 未返回有效分析结果")
        return merged

    def _normalize_expert_payload(self, payload: dict[str, Any], default: dict[str, Any]) -> dict[str, Any]:
        merged = dict(default)
        merged["summary"] = self._pick_text(
            payload,
            "summary",
            "conclusion",
            "view",
            "opinion",
            "analysis",
            "judgement",
        )
        merged["signals"] = self._to_bullet_list(
            payload.get("signals")
            or payload.get("signal_list")
            or payload.get("highlights")
            or payload.get("positive_signals")
        )
        merged["risks"] = self._to_bullet_list(
            payload.get("risks")
            or payload.get("risk_points")
            or payload.get("risk_list")
            or payload.get("negative_signals")
        )
        merged["confidence"] = self._to_confidence(payload.get("confidence"), default.get("confidence", 0.0))

        if "recommendation" in default:
            merged["recommendation"] = (
                self._pick_text(payload, "recommendation", "suggestion", "advice", "action")
                or default.get("recommendation", "")
            )

        if not merged["risks"] and isinstance(payload.get("risks"), dict):
            merged["risks"] = self._to_bullet_list(payload["risks"].get("risks_list"))

        if not merged["summary"] and merged["signals"]:
            merged["summary"] = merged["signals"][0]

        return merged

    def _pick_text(self, payload: dict[str, Any], *keys: str) -> str:
        for key in keys:
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    def _to_bullet_list(self, value: Any) -> list[str]:
        if value in (None, "", []):
            return []
        if isinstance(value, str):
            item = self._normalize_list_item(value)
            return [item] if item else []
        if isinstance(value, dict):
            items: list[str] = []
            for nested in value.values():
                items.extend(self._to_bullet_list(nested))
            return items[:6]
        if not isinstance(value, list):
            item = self._normalize_list_item(str(value))
            return [item] if item else []

        items: list[str] = []
        for item in value:
            if isinstance(item, str) and item.strip():
                text = self._normalize_list_item(item)
                if text:
                    items.append(text)
                continue
            if isinstance(item, dict):
                text = (
                    self._pick_dict_text(item, "description", "summary", "signal", "risk", "rationale", "title", "type")
                    or str(item)
                )
                text = self._normalize_list_item(text)
                if text:
                    items.append(text)
                continue
            text = self._normalize_list_item(str(item))
            if text:
                items.append(text)
        return items[:6]

    def _normalize_list_item(self, value: str) -> str:
        text = " ".join(str(value).split()).strip()
        if not text:
            return ""
        leading = "；;，,、。.!！?？：:"
        trailing = "；;，,、。.!！?？"
        text = text.lstrip(leading).rstrip(trailing).strip()
        return text

    def _pick_dict_text(self, payload: dict[str, Any], *keys: str) -> str:
        for key in keys:
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value
        return ""

    def _to_confidence(self, value: Any, default: float) -> float:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return float(default)
        return max(0.0, min(1.0, numeric))
