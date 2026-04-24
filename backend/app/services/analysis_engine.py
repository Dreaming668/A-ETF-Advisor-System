from __future__ import annotations

import math
from collections import Counter
from statistics import mean, pstdev

from sqlalchemy import desc, select

from ..models import ETFConstituent, ETFFactor, ETFMaster, ETFNews, ETFQuote, RiskQuestionnaireSubmission
from .agent_orchestrator import AgentOrchestrator
from .llm_provider import provider_status as llm_provider_status


RISK_ORDER = {"保守型": 1, "稳健型": 2, "平衡型": 3, "积极型": 4, "激进型": 5}


def risk_rank(level: str) -> int:
    return RISK_ORDER.get(level, 3)


class AnalysisService:
    def __init__(self, session):
        self.session = session

    def build_analysis(self, etf_code: str, user_id: str, mode: str = "llm") -> dict:
        etf = self.session.get(ETFMaster, etf_code)
        if not etf:
            raise ValueError("ETF not found")

        quotes = list(self.session.scalars(select(ETFQuote).where(ETFQuote.etf_code == etf_code).order_by(ETFQuote.trade_date.asc())))
        news = list(self.session.scalars(select(ETFNews).where(ETFNews.etf_code == etf_code).order_by(desc(ETFNews.published_at)).limit(8)))
        factor = self.session.scalar(select(ETFFactor).where(ETFFactor.etf_code == etf_code).order_by(desc(ETFFactor.as_of)).limit(1))
        constituents = list(self.session.scalars(select(ETFConstituent).where(ETFConstituent.etf_code == etf_code)))
        profile = self.session.scalar(select(RiskQuestionnaireSubmission).where(RiskQuestionnaireSubmission.user_id == user_id).order_by(desc(RiskQuestionnaireSubmission.created_at)).limit(1))

        if not quotes:
            raise ValueError("No live market data found. Please refresh the ETF dataset first.")
        latest = quotes[-1]
        recent_20 = quotes[-20:] if len(quotes) >= 20 else quotes
        recent_60 = quotes[-60:] if len(quotes) >= 60 else quotes
        returns = [q.pct_change / 100 for q in recent_20 if q.pct_change is not None]
        change_20 = (latest.close_price / recent_20[0].close_price - 1) * 100 if recent_20 else 0.0
        change_60 = (latest.close_price / recent_60[0].close_price - 1) * 100 if recent_60 else 0.0
        annualized_vol = pstdev(returns) * math.sqrt(252) * 100 if len(returns) > 1 else 0.0
        avg_turnover_20 = mean(q.turnover for q in recent_20) if recent_20 else latest.turnover
        turnover_ratio = latest.turnover / avg_turnover_20 if avg_turnover_20 else 1.0
        news_sentiment = mean([n.sentiment for n in news]) if news else 0.0

        analysis = {
            "etf": {
                "code": etf.code,
                "name": etf.name,
                "category": etf.category,
                "theme": etf.theme,
                "benchmark": etf.benchmark,
                "risk_level": etf.risk_level,
                "description": etf.description,
            },
            "latest_quote": {
                "trade_date": latest.trade_date.isoformat(),
                "close_price": round(latest.close_price, 4),
                "pct_change": round(latest.pct_change, 2),
                "turnover": round(latest.turnover, 2),
                "change_20d": round(change_20, 2),
                "change_60d": round(change_60, 2),
                "annualized_volatility": round(annualized_vol, 2),
                "turnover_ratio": round(turnover_ratio, 2),
            },
            "quotes": [
                {
                    "trade_date": q.trade_date.isoformat(),
                    "close_price": q.close_price,
                    "pct_change": q.pct_change,
                    "turnover": q.turnover,
                }
                for q in quotes[-40:]
            ],
            "news": [
                {
                    "title": n.title,
                    "source": n.source,
                    "published_at": n.published_at.isoformat(timespec="seconds"),
                    "sentiment": n.sentiment,
                    "summary": n.summary,
                }
                for n in news
            ],
            "constituents": [
                {
                    "stock_code": item.stock_code,
                    "stock_name": item.stock_name,
                    "weight": round(item.weight, 2),
                    "pe": round(item.pe, 2),
                    "pb": round(item.pb, 2),
                    "roe": round(item.roe, 2),
                    "revenue_growth": round(item.revenue_growth, 2),
                    "profit_growth": round(item.profit_growth, 2),
                    "sector": item.sector,
                }
                for item in sorted(constituents, key=lambda row: row.weight, reverse=True)[:10]
            ],
            "factor": {
                "as_of": factor.as_of.isoformat() if factor else None,
                "momentum": factor.momentum if factor else 0,
                "volatility": factor.volatility if factor else 0,
                "liquidity": factor.liquidity if factor else 0,
                "money_flow": factor.money_flow if factor else 0,
                "valuation": factor.valuation if factor else 0,
                "industry_rotation": factor.industry_rotation if factor else 0,
                "composite_score": factor.composite_score if factor else 0,
            },
            "experts": {
                "market": {"name": "市场专家", "summary": "", "signals": [], "risks": [], "confidence": 0.0},
                "news": {"name": "新闻分析师", "summary": "", "signals": [], "risks": [], "confidence": 0.0},
                "alpha": {"name": "Alpha分析师", "summary": "", "signals": [], "risks": [], "confidence": 0.0},
                "fundamental": {"name": "基本面分析师", "summary": "", "signals": [], "risks": [], "confidence": 0.0},
                "general": {"name": "通用专家", "summary": "", "signals": [], "risks": [], "confidence": 0.0, "recommendation": ""},
            },
            "risk_profile": {
                "risk_level": profile.risk_level if profile else "平衡型",
                "preference_tags": profile.preference_tags.split(",") if profile else ["宽基", "中期配置"],
                "investment_horizon": profile.investment_horizon if profile else "中期",
                "max_drawdown": profile.max_drawdown if profile else "10%-15%",
            },
            "sources": [
                {"name": "腾讯财经/新浪财经 ETF 行情", "type": "market_data"},
                {"name": "国内财经站点聚合新闻", "type": "news"},
                {"name": "东方财富 ETF 持仓 + 东方财富/新浪个股财务", "type": "fundamental_factor"},
            ],
            "model_provider": llm_provider_status(),
            "agent_mode": "llm_pending",
        }

        if mode == "auto":
            mode = "llm"
        if mode != "llm":
            raise ValueError("Rule-based analysis has been disabled. Please use mode='llm'.")

        return AgentOrchestrator("openai").enrich_analysis(analysis)

    def _market_expert(self, change_20, annualized_vol, turnover_ratio, latest):
        trend = "震荡"
        if change_20 > 4 and latest.pct_change >= 0:
            trend = "偏强上行"
        elif change_20 < -4:
            trend = "弱势回撤"
        signals = [f"近20日{'累计上涨' if change_20 > 0 else '累计回撤'} {abs(change_20):.2f}%"]
        if turnover_ratio > 1.1:
            signals.append(f"最新成交额约为20日均值的 {turnover_ratio:.2f} 倍")
        signals.append("短期波动放大，交易拥挤度偏高" if annualized_vol > 28 else "波动仍处于可控区间")
        risks = []
        if annualized_vol > 30:
            risks.append("高波动环境下追涨回撤风险上升")
        if latest.pct_change < -1.5:
            risks.append("近期出现较明显的单日回落，需关注趋势破位风险")
        if not risks:
            risks.append("当前主要风险来自风格轮动速度变化")
        return {
            "name": "市场专家",
            "summary": f"量价面显示 {trend}，最新收盘价 {latest.close_price:.4f}，短期趋势与成交活跃度仍具参考价值。",
            "signals": signals,
            "risks": risks,
            "confidence": 0.74,
        }

    def _news_expert(self, news, news_sentiment):
        sentiment_label = "中性"
        if news_sentiment >= 0.15:
            sentiment_label = "偏利多"
        elif news_sentiment <= -0.1:
            sentiment_label = "偏利空"
        return {
            "name": "新闻分析师",
            "summary": f"近期资讯情绪整体为 {sentiment_label}，事件更多聚焦在政策催化、景气度变化和成分股业绩预期。",
            "signals": [f"{n.title} | {n.summary}" for n in news[:3]] or ["暂无重要新闻"],
            "risks": ["消息驱动品种容易在情绪降温时出现回吐", "新闻影响通常短于基本面影响"],
            "confidence": 0.68,
        }

    def _alpha_expert(self, factor):
        if not factor:
            return {"name": "Alpha分析师", "summary": "暂无因子数据。", "signals": [], "risks": [], "confidence": 0.4}
        highlights = []
        if factor.momentum >= 75:
            highlights.append("动量因子排名靠前")
        if factor.money_flow >= 70:
            highlights.append("资金流因子偏强")
        if factor.liquidity >= 75:
            highlights.append("流动性良好")
        if factor.valuation <= 50:
            highlights.append("估值因子约束偏弱，性价比一般")
        risks = ["当复合因子分数高但波动因子同步抬升时，需要防止拥挤交易。"]
        if factor.volatility >= 70:
            risks.append("高波动因子提示仓位不宜过满。")
        return {
            "name": "Alpha分析师",
            "summary": f"综合因子得分 {factor.composite_score:.0f} 分，当前风格适配性处于中上水平。",
            "signals": highlights,
            "risks": risks,
            "confidence": 0.72,
        }

    def _fundamental_expert(self, constituents):
        total_weight = sum(item.weight for item in constituents)
        weighted_mode = total_weight > 0.01
        if not weighted_mode:
            total_weight = len(constituents) or 1
        avg_pe = sum(item.pe * item.weight for item in constituents) / total_weight
        avg_pb = sum(item.pb * item.weight for item in constituents) / total_weight
        avg_roe = sum(item.roe * item.weight for item in constituents) / total_weight
        avg_rev = sum(item.revenue_growth * item.weight for item in constituents) / total_weight
        avg_profit = sum(item.profit_growth * item.weight for item in constituents) / total_weight
        if not weighted_mode:
            avg_pe = sum(item.pe for item in constituents) / total_weight
            avg_pb = sum(item.pb for item in constituents) / total_weight
            avg_roe = sum(item.roe for item in constituents) / total_weight
            avg_rev = sum(item.revenue_growth for item in constituents) / total_weight
            avg_profit = sum(item.profit_growth for item in constituents) / total_weight
        sector_counter = Counter()
        for item in constituents:
            sector_counter[item.sector] += item.weight if weighted_mode else 1
        top_sector, top_sector_weight = sector_counter.most_common(1)[0]
        signals = [
            f"权重股加权 ROE 约 {avg_roe:.1f}%",
            f"收入增速约 {avg_rev:.1f}%，利润增速约 {avg_profit:.1f}%",
            f"第一大行业暴露为 {top_sector}，权重约 {top_sector_weight:.1f}{'%' if weighted_mode else '（旧数据按等权兜底）'}",
        ]
        risks = []
        if top_sector_weight > 20:
            risks.append(f"{top_sector} 行业集中度偏高，单一赛道波动会更快传导。")
        if avg_pe > 30:
            risks.append("成分股整体估值不低，需要更关注业绩兑现。")
        if not risks:
            risks.append("基本面整体稳健，但需持续关注权重股业绩兑现。")
        return {
            "name": "基本面分析师",
            "summary": f"组合层面估值约 PE {avg_pe:.1f} / PB {avg_pb:.1f}，底层资产质量处于可接受区间。",
            "signals": signals,
            "risks": risks,
            "confidence": 0.7,
        }

    def _general_expert(self, etf, factor, profile, market_expert, fundamental_expert, change_20, news_sentiment):
        market_expert = market_expert or {"signals": []}
        fundamental_expert = fundamental_expert or {"signals": []}
        composite = factor.composite_score if factor else 60
        profile_level = profile.risk_level if profile else "平衡型"
        fit_gap = risk_rank(profile_level) - risk_rank(etf.risk_level)
        score = composite * 0.55 + max(-10, min(10, change_20)) * 1.4 + news_sentiment * 12
        score += 4 if "波动仍处于可控区间" in market_expert.get("signals", []) else 0
        score += 3 if "ROE" in " ".join(fundamental_expert.get("signals", [])) else 0
        score += fit_gap * 5
        recommendation = "控制仓位"
        if score >= 62:
            recommendation = "分批布局"
        elif score >= 54:
            recommendation = "继续持有"
        elif score >= 46:
            recommendation = "关注观察"
        if fit_gap < -1 and recommendation == "分批布局":
            recommendation = "小仓位关注"
        confidence = max(0.52, min(0.89, 0.58 + composite / 200 + news_sentiment / 4))
        fit_text = "与用户风险等级较匹配"
        if fit_gap <= -2:
            fit_text = "ETF 风险高于用户画像，建议更谨慎"
        elif fit_gap >= 1:
            fit_text = "用户风险承受能力覆盖该 ETF 波动"
        summary = f"综合量价、资讯、因子与基本面后，当前更适合采取“{recommendation}”思路。{fit_text}，若未来 3 至 5 个交易日维持成交与趋势共振，配置胜率会更高。"
        risks = [
            "若市场风格突然切回低波红利，成长或主题类 ETF 弹性可能回落。",
            "若成交额明显萎缩，短期信号可信度会下降。",
        ]
        if risk_rank(etf.risk_level) > risk_rank(profile_level):
            risks.append("当前产品风险高于你的风险画像，建议降低单品集中度。")
        return {
            "name": "通用专家",
            "summary": summary,
            "signals": [f"综合得分约 {score:.1f}", f"用户画像：{profile_level}", f"产品风险等级：{etf.risk_level}"],
            "risks": risks,
            "confidence": round(confidence, 2),
            "recommendation": recommendation,
        }
