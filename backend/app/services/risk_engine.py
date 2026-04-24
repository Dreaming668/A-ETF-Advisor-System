from __future__ import annotations

from dataclasses import dataclass


SCORE_MAP = {
    "age_range": {
        "18-25": 14,
        "26-35": 12,
        "36-45": 10,
        "46-55": 7,
        "55+": 5,
    },
    "investment_experience": {
        "无经验": 4,
        "1年以内": 7,
        "1-3年": 10,
        "3-5年": 12,
        "5年以上": 15,
    },
    "risk_tolerance": {
        "可接受5%以内回撤": 5,
        "可接受5%-10%回撤": 8,
        "可接受10%-15%回撤": 11,
        "可接受15%-20%回撤": 14,
        "可接受20%以上回撤": 17,
    },
    "investment_goal": {
        "保值": 5,
        "稳健增值": 9,
        "追求超额收益": 13,
        "追求高弹性成长": 16,
    },
    "holding_period": {
        "短期": 11,
        "中期": 9,
        "长期": 12,
    },
    "liquidity_need": {
        "高": 4,
        "中等": 8,
        "低": 11,
    },
}


@dataclass
class RiskProfileResult:
    total_score: int
    risk_level: str
    preference_tags: list[str]
    investment_horizon: str
    max_drawdown: str
    summary: str


class RiskEngine:
    def evaluate(self, answers: dict[str, str]) -> RiskProfileResult:
        total_score = 0
        for field, mapping in SCORE_MAP.items():
            total_score += mapping.get(answers.get(field, ""), 0)

        if total_score >= 76:
            risk_level = "激进型"
        elif total_score >= 66:
            risk_level = "积极型"
        elif total_score >= 56:
            risk_level = "平衡型"
        elif total_score >= 44:
            risk_level = "稳健型"
        else:
            risk_level = "保守型"

        sector_preference = answers.get("sector_preference", "宽基")
        holding_period = answers.get("holding_period", "中期")
        max_drawdown = answers.get("risk_tolerance", "可接受5%-10%回撤").replace("可接受", "")
        preference_tags = [sector_preference, holding_period]

        if risk_level in {"保守型", "稳健型"}:
            preference_tags.append("低波动")
            summary = "你的画像偏稳健，建议以宽基、红利或大盘蓝筹 ETF 为核心，控制高弹性主题仓位。"
        elif risk_level == "平衡型":
            preference_tags.append("均衡配置")
            summary = "你的画像较均衡，可在宽基 ETF 的基础上适度配置成长或行业主题 ETF，采用分批布局。"
        else:
            preference_tags.append("成长弹性")
            summary = "你的风险承受能力较强，可适当关注成长和行业主题 ETF，但仍需设置回撤边界和仓位纪律。"

        return RiskProfileResult(
            total_score=total_score,
            risk_level=risk_level,
            preference_tags=preference_tags,
            investment_horizon=holding_period,
            max_drawdown=max_drawdown,
            summary=summary,
        )
