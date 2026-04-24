from __future__ import annotations

import re
from statistics import mean

from sqlalchemy import desc, select

from ..models import (
    AnalysisReport,
    ChatMessage,
    ChatSession,
    ETFConstituent,
    ETFFactor,
    ETFMaster,
    ETFNews,
    ETFQuote,
    RiskQuestionnaireSubmission,
)
from .llm_provider import resolve_provider


CHAT_THINKING_STEPS = [
    "读取 ETF 上下文",
    "整理行情、新闻与因子线索",
    "生成投顾建议",
]

RISK_ORDER = {"保守型": 1, "稳健型": 2, "平衡型": 3, "积极型": 4, "激进型": 5}


class ChatService:
    def __init__(self, session):
        self.session = session

    def create_session(self, user_id: str, etf_code: str | None) -> ChatSession:
        title = f"{etf_code or '通用'}投顾会话"
        chat_session = ChatSession(user_id=user_id, etf_code=etf_code, title=title)
        self.session.add(chat_session)
        self.session.flush()
        return chat_session

    def reply(self, session_id: int, content: str) -> ChatMessage:
        chat_session = self.session.get(ChatSession, session_id)
        if not chat_session:
            raise ValueError("Chat session not found")

        user_message = ChatMessage(session_id=session_id, role="user", content=content)
        self.session.add(user_message)
        self.session.flush()

        if not chat_session.etf_code:
            answer = "这条会话还没有绑定 ETF，请先在左侧选择目标 ETF，再发起提问。"
        else:
            context = self._build_chat_context(chat_session)
            answer = self._generate_llm_answer(content, context)

        assistant = ChatMessage(
            session_id=session_id,
            role="assistant",
            expert_name="通用专家",
            content=self._clean_reply_text(answer),
        )
        assistant.thinking_steps = list(CHAT_THINKING_STEPS)
        self.session.add(assistant)
        self.session.flush()
        return assistant

    def _build_chat_context(self, chat_session: ChatSession) -> dict:
        etf = self.session.get(ETFMaster, chat_session.etf_code)
        if not etf:
            raise ValueError("ETF not found")

        quotes = list(
            reversed(
                list(
                    self.session.scalars(
                        select(ETFQuote)
                        .where(ETFQuote.etf_code == chat_session.etf_code)
                        .order_by(desc(ETFQuote.trade_date))
                        .limit(60)
                    )
                )
            )
        )
        news = list(
            self.session.scalars(
                select(ETFNews)
                .where(ETFNews.etf_code == chat_session.etf_code)
                .order_by(desc(ETFNews.published_at))
                .limit(5)
            )
        )
        factor = self.session.scalar(
            select(ETFFactor)
            .where(ETFFactor.etf_code == chat_session.etf_code)
            .order_by(desc(ETFFactor.as_of))
            .limit(1)
        )
        constituents = list(
            self.session.scalars(
                select(ETFConstituent)
                .where(ETFConstituent.etf_code == chat_session.etf_code)
                .order_by(desc(ETFConstituent.weight))
                .limit(5)
            )
        )
        profile = self.session.scalar(
            select(RiskQuestionnaireSubmission)
            .where(RiskQuestionnaireSubmission.user_id == chat_session.user_id)
            .order_by(desc(RiskQuestionnaireSubmission.created_at))
            .limit(1)
        )
        latest_report = self.session.scalar(
            select(AnalysisReport)
            .where(
                AnalysisReport.user_id == chat_session.user_id,
                AnalysisReport.etf_code == chat_session.etf_code,
            )
            .order_by(desc(AnalysisReport.created_at))
            .limit(1)
        )
        history = list(
            reversed(
                list(
                    self.session.scalars(
                        select(ChatMessage)
                        .where(ChatMessage.session_id == chat_session.id)
                        .order_by(desc(ChatMessage.created_at))
                        .limit(8)
                    )
                )
            )
        )

        latest_quote = quotes[-1] if quotes else None
        recent_5 = quotes[-5:] if len(quotes) >= 5 else quotes
        recent_20 = quotes[-20:] if len(quotes) >= 20 else quotes
        change_5d = self._calc_change(recent_5)
        change_20d = self._calc_change(recent_20)
        avg_turnover_20 = mean(item.turnover for item in recent_20) if recent_20 else None
        sentiment = round(mean(item.sentiment for item in news), 2) if news else 0.0

        return {
            "etf": {
                "code": etf.code,
                "name": etf.name,
                "category": etf.category,
                "theme": etf.theme,
                "benchmark": etf.benchmark,
                "risk_level": etf.risk_level,
                "description": etf.description,
            },
            "risk_profile": {
                "risk_level": profile.risk_level if profile else "平衡型",
                "investment_horizon": profile.investment_horizon if profile else "中期",
                "max_drawdown": profile.max_drawdown if profile else "10%-15%",
                "summary": profile.summary if profile else "当前为默认风险画像，建议结合实际问卷结果使用。",
            },
            "latest_quote": {
                "trade_date": latest_quote.trade_date.isoformat() if latest_quote else "暂无",
                "close_price": round(latest_quote.close_price, 4) if latest_quote else None,
                "pct_change": round(latest_quote.pct_change, 2) if latest_quote else None,
                "change_5d": change_5d,
                "change_20d": change_20d,
                "turnover": round(latest_quote.turnover, 2) if latest_quote else None,
                "turnover_vs_20d_avg": round(latest_quote.turnover / avg_turnover_20, 2)
                if latest_quote and avg_turnover_20
                else None,
            },
            "factor": {
                "as_of": factor.as_of.isoformat() if factor else None,
                "momentum": round(factor.momentum, 1) if factor else None,
                "volatility": round(factor.volatility, 1) if factor else None,
                "liquidity": round(factor.liquidity, 1) if factor else None,
                "money_flow": round(factor.money_flow, 1) if factor else None,
                "valuation": round(factor.valuation, 1) if factor else None,
                "industry_rotation": round(factor.industry_rotation, 1) if factor else None,
                "composite_score": round(factor.composite_score, 1) if factor else None,
            },
            "news_summary": {
                "count": len(news),
                "average_sentiment": sentiment,
                "items": [
                    {
                        "title": item.title,
                        "source": item.source,
                        "published_at": item.published_at.isoformat(timespec="seconds"),
                        "summary": item.summary,
                    }
                    for item in news
                ],
            },
            "top_constituents": [
                {
                    "stock_name": item.stock_name,
                    "stock_code": item.stock_code,
                    "weight": round(item.weight, 2),
                    "pe": round(item.pe, 2),
                    "pb": round(item.pb, 2),
                    "roe": round(item.roe, 2),
                    "sector": item.sector,
                }
                for item in constituents
            ],
            "latest_report": {
                "title": latest_report.title,
                "summary": latest_report.summary,
                "recommendation": latest_report.recommendation,
                "confidence": round(latest_report.confidence, 2),
                "created_at": latest_report.created_at.isoformat(timespec="seconds"),
            }
            if latest_report
            else None,
            "recent_history": [
                {
                    "role": item.role,
                    "expert_name": item.expert_name,
                    "content": item.content,
                }
                for item in history
            ],
        }

    def _generate_llm_answer(self, content: str, context: dict) -> str:
        provider = resolve_provider("openai")
        developer_prompt = (
            "你是 A 股 ETF 智能投顾助手，负责进行多轮追问回答。"
            "请只基于提供的 ETF、行情、新闻、因子、基本面、风险画像和历史对话作答。"
            "回答必须自然、直接、专业，优先解决用户当前问题，不要复述整份报告。"
            "如果用户问题已经具体，第一句话就直接回答结论，不要先反问，不要给用户列菜单。"
            "如果用户在问买卖、加仓、减仓、风险、仓位，请结合风险画像给出谨慎建议，不要承诺收益。"
            "输出要求："
            "1. 使用简洁中文，避免模板腔和空话；"
            "2. 不要使用重复标点、异常空格、连串分号；"
            "3. 默认控制在 120 到 220 字，必要时最多 3 小段；"
            "4. 若数据不足，要明确指出缺口；"
            "5. 不要暴露内部推理过程，也不要说自己调用了模型；"
            "6. 禁止输出“你可以问我”“请选择一项”“我可以从几个角度分析”等引导式菜单，除非用户的问题本身明显过于模糊；"
            "7. 严格输出 JSON 对象，字段为 answer 和 need_clarification，其中 answer 是给用户的最终回复。"
        )
        user_prompt = (
            f"ETF 上下文：\n{self._format_context(context)}\n\n"
            f"最近对话：\n{self._format_history(context['recent_history'])}\n\n"
            f"用户本轮问题：{content}\n\n"
            "请输出 JSON："
            "{\"answer\":\"...\",\"need_clarification\":false}。"
            "若问题已经足够具体，务必直接作答，不要先澄清。"
            "只有当用户问题极度模糊、无法判断意图时，need_clarification 才能为 true。"
        )
        payload = provider.generate_json(
            developer_prompt,
            user_prompt,
            default={"answer": "", "need_clarification": False},
        )
        answer = str(payload.get("answer", "")).strip()
        if answer:
            if not self._is_low_signal_reply(answer):
                return answer
        fallback = provider.generate_text(developer_prompt, user_prompt, max_output_tokens=420)
        if not self._is_low_signal_reply(fallback):
            return fallback
        return self._generate_fallback_answer(content, context)

    @staticmethod
    def _format_context(context: dict) -> str:
        etf = context["etf"]
        risk_profile = context["risk_profile"]
        latest_quote = context["latest_quote"]
        factor = context["factor"]
        news_summary = context["news_summary"]
        top_constituents = context["top_constituents"]
        latest_report = context["latest_report"]

        lines = [
            f"ETF：{etf['name']}（{etf['code']}），分类={etf['category']}，主题={etf['theme']}，基准={etf['benchmark']}，产品风险={etf['risk_level']}。",
            f"ETF简介：{etf['description']}",
            (
                f"用户画像：风险={risk_profile['risk_level']}，期限={risk_profile['investment_horizon']}，"
                f"最大回撤={risk_profile['max_drawdown']}，画像摘要={risk_profile['summary']}"
            ),
            (
                f"最新行情：交易日={latest_quote['trade_date']}，收盘价={latest_quote['close_price']}，"
                f"单日涨跌={latest_quote['pct_change']}%，近5日={latest_quote['change_5d']}%，"
                f"近20日={latest_quote['change_20d']}%，成交额/20日均值={latest_quote['turnover_vs_20d_avg']}"
            ),
            (
                f"最新因子：日期={factor['as_of']}，综合得分={factor['composite_score']}，动量={factor['momentum']}，"
                f"波动={factor['volatility']}，流动性={factor['liquidity']}，资金流={factor['money_flow']}，估值={factor['valuation']}"
            ),
            f"新闻概况：近{news_summary['count']}条，平均情绪={news_summary['average_sentiment']}。",
        ]

        if news_summary["items"]:
            lines.append(
                "最近新闻："
                + " | ".join(
                    f"{item['title']}（{item['source']}，{item['published_at']}）摘要：{item['summary']}"
                    for item in news_summary["items"][:3]
                )
            )
        else:
            lines.append("最近新闻：暂无。")

        if top_constituents:
            lines.append(
                "前五大成分股："
                + " | ".join(
                    f"{item['stock_name']}({item['stock_code']}) 权重{item['weight']}%，PE {item['pe']}，ROE {item['roe']}%，行业={item['sector']}"
                    for item in top_constituents
                )
            )
        else:
            lines.append("前五大成分股：暂无。")

        if latest_report:
            lines.append(
                f"最近报告：{latest_report['created_at']} 生成，标题={latest_report['title']}，"
                f"建议={latest_report['recommendation']}，置信度={latest_report['confidence']}，摘要={latest_report['summary']}"
            )
        else:
            lines.append("最近报告：暂无历史报告。")

        return "\n".join(lines)

    @staticmethod
    def _format_history(history: list[dict]) -> str:
        if not history:
            return "暂无历史对话。"
        lines = []
        for item in history[-6:]:
            speaker = "用户" if item["role"] == "user" else (item.get("expert_name") or "通用专家")
            lines.append(f"{speaker}：{item['content']}")
        return "\n".join(lines)

    @staticmethod
    def _calc_change(quotes: list[ETFQuote]) -> float | None:
        if len(quotes) < 2:
            return None
        base = quotes[0].close_price
        if not base:
            return None
        return round((quotes[-1].close_price / base - 1) * 100, 2)

    def _generate_fallback_answer(self, content: str, context: dict) -> str:
        etf = context["etf"]
        risk_profile = context["risk_profile"]
        latest_quote = context["latest_quote"]
        factor = context["factor"]
        news_summary = context["news_summary"]
        latest_report = context["latest_report"]

        question = content.lower()
        sentiment = float(news_summary.get("average_sentiment") or 0)
        sentiment_label = "中性"
        if sentiment >= 0.15:
            sentiment_label = "偏多"
        elif sentiment <= -0.15:
            sentiment_label = "偏空"

        change_20d = latest_quote.get("change_20d")
        turnover_ratio = latest_quote.get("turnover_vs_20d_avg")
        composite_score = factor.get("composite_score")
        volatility = factor.get("volatility")
        momentum = factor.get("momentum")

        stance = "更适合先观察"
        if composite_score is not None and change_20d is not None:
            if composite_score >= 70 and change_20d >= 3:
                stance = "可以考虑分批加仓"
            elif composite_score >= 55 and change_20d >= -2:
                stance = "更适合小步分批布局"

        risk_items = []
        if volatility is not None and volatility >= 70:
            risk_items.append("波动因子偏高，短线回撤会更大")
        if momentum is not None and momentum <= 40:
            risk_items.append("动量偏弱，追高胜率一般")
        if turnover_ratio is not None and turnover_ratio < 0.85:
            risk_items.append("成交活跃度不强，持续性要再观察")
        if self._risk_rank(etf["risk_level"]) > self._risk_rank(risk_profile["risk_level"]):
            risk_items.append("产品风险高于你的画像，仓位不宜过重")
        if not risk_items:
            risk_items.append("主要风险来自风格切换和消息面反复")

        report_hint = ""
        if latest_report:
            report_hint = f" 最近一次综合建议是“{latest_report['recommendation']}”。"

        if any(keyword in question for keyword in ["新闻", "消息", "资讯"]):
            return (
                f"{etf['name']} 最近新闻情绪整体{sentiment_label}，近{news_summary['count']}条新闻的平均情绪为 {sentiment:.2f}。"
                f" 从投顾角度看，当前更需要留意的是{risk_items[0]}。{report_hint}"
            )

        if any(keyword in question for keyword in ["风险", "回撤", "会不会跌", "下跌"]):
            return (
                f"{etf['name']} 当前最需要注意的是{risk_items[0]}，其次是{risk_items[1] if len(risk_items) > 1 else '市场风格切换带来的波动'}。"
                f" 以你当前{risk_profile['risk_level']}画像看，更适合分批而不是重仓单押。{report_hint}"
            )

        if any(keyword in question for keyword in ["加仓", "买入", "建仓", "适合", "仓位"]):
            return (
                f"以你当前{risk_profile['risk_level']}画像看，{etf['name']} 现阶段{stance}。"
                f" 近20日涨跌幅为 {change_20d}%，综合因子得分为 {composite_score}，新闻情绪{sentiment_label}。"
                f" 更稳妥的做法是分批进，不建议一次性重仓。{report_hint}"
            )

        return (
            f"{etf['name']} 当前更适合结合行情和风险画像谨慎处理。"
            f" 近20日涨跌幅 {change_20d}%，综合因子得分 {composite_score}，新闻情绪{sentiment_label}。"
            f" 如果你准备操作，我更倾向于{stance}，同时注意{risk_items[0]}。{report_hint}"
        )

    @staticmethod
    def _risk_rank(level: str) -> int:
        return RISK_ORDER.get(level, 3)

    @staticmethod
    def _is_low_signal_reply(text: str) -> bool:
        normalized = str(text or "").strip().lower()
        if not normalized:
            return True
        generic_markers = [
            "i’m not sure what you need",
            "i'm not sure what you need",
            "how can i help",
            "what would you like to do or ask about",
            "can you clarify",
            "tell me what you need",
            "pick one",
            "你可以问我",
            "请选择一项",
            "我没看懂你的问题",
            "看起来您没输入具体问题",
            "看起来你有疑问",
            "可以从几个角度",
        ]
        return any(marker in normalized for marker in generic_markers)

    @staticmethod
    def _clean_reply_text(text: str) -> str:
        value = str(text or "").strip().replace("\r\n", "\n")
        if not value:
            return "这轮问题我暂时没有生成有效回答，你可以换个问法再试一次。"

        replacements = [
            ("；。", "。"),
            ("。；", "。"),
            ("，。", "。"),
            ("。。", "。"),
            ("，，", "，"),
            ("；；", "；"),
            ("：：", "："),
            ("、、", "、"),
            ("\n；", "\n"),
        ]
        for old, new in replacements:
            while old in value:
                value = value.replace(old, new)

        value = re.sub(r"[ \t]+", " ", value)
        value = re.sub(r"\s+([，。；：、！？])", r"\1", value)
        value = re.sub(r"([，；：、])([，；：、])+", r"\1", value)
        value = re.sub(r"。{2,}", "。", value)
        value = re.sub(r"\n{3,}", "\n\n", value)
        value = re.sub(r"([。！？])\n(?=[。！？])", r"\1", value)
        return value.strip()
