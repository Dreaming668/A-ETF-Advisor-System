from __future__ import annotations

import math
import random
from datetime import date, datetime, timedelta

from sqlalchemy import select

from .database import session_scope
from .models import (
    ETFConstituent,
    ETFFactor,
    ETFMaster,
    ETFNews,
    ETFQuote,
    RiskQuestionnaireSubmission,
    User,
)


ETF_DATA = [
    {
        "code": "510300",
        "name": "沪深300ETF",
        "category": "宽基",
        "theme": "大盘核心资产",
        "benchmark": "沪深300指数",
        "risk_level": "平衡型",
        "description": "覆盖沪深两市核心龙头，兼具流动性与代表性，适合中长期配置。",
        "base_price": 3.82,
        "drift": 0.0012,
        "volatility": 0.011,
        "news_bias": 0.12,
        "factor": {"momentum": 73, "volatility": 48, "liquidity": 88, "money_flow": 66, "valuation": 61, "industry_rotation": 58, "composite": 69},
    },
    {
        "code": "510050",
        "name": "上证50ETF",
        "category": "宽基",
        "theme": "央国企蓝筹",
        "benchmark": "上证50指数",
        "risk_level": "稳健型",
        "description": "偏向大市值蓝筹和金融权重，波动相对可控，适合稳健型用户。",
        "base_price": 2.67,
        "drift": 0.0009,
        "volatility": 0.009,
        "news_bias": 0.05,
        "factor": {"momentum": 61, "volatility": 44, "liquidity": 82, "money_flow": 59, "valuation": 65, "industry_rotation": 52, "composite": 63},
    },
    {
        "code": "159915",
        "name": "创业板ETF",
        "category": "成长",
        "theme": "科技成长",
        "benchmark": "创业板指数",
        "risk_level": "积极型",
        "description": "聚焦成长风格和科技赛道，弹性较大，适合风险承受能力较强用户。",
        "base_price": 1.91,
        "drift": 0.0017,
        "volatility": 0.017,
        "news_bias": 0.18,
        "factor": {"momentum": 84, "volatility": 69, "liquidity": 74, "money_flow": 79, "valuation": 43, "industry_rotation": 81, "composite": 76},
    },
    {
        "code": "512100",
        "name": "中证1000ETF",
        "category": "宽基",
        "theme": "中小盘弹性",
        "benchmark": "中证1000指数",
        "risk_level": "积极型",
        "description": "对中小盘风格暴露更高，风格轮动收益弹性较强，但回撤也更明显。",
        "base_price": 2.24,
        "drift": 0.0014,
        "volatility": 0.015,
        "news_bias": 0.08,
        "factor": {"momentum": 78, "volatility": 63, "liquidity": 68, "money_flow": 71, "valuation": 58, "industry_rotation": 75, "composite": 72},
    },
    {
        "code": "515880",
        "name": "通信ETF",
        "category": "行业",
        "theme": "通信算力",
        "benchmark": "中证全指通信设备指数",
        "risk_level": "激进型",
        "description": "行业主题鲜明，受政策、订单和市场情绪影响更大，波动高于宽基 ETF。",
        "base_price": 1.36,
        "drift": 0.0019,
        "volatility": 0.019,
        "news_bias": 0.21,
        "factor": {"momentum": 87, "volatility": 74, "liquidity": 61, "money_flow": 76, "valuation": 46, "industry_rotation": 85, "composite": 78},
    },
]

CONSTITUENTS = {
    "510300": [
        ("600519", "贵州茅台", 8.2, 29.0, 9.6, 33.0, 15.0, 18.0, "消费"),
        ("300750", "宁德时代", 5.6, 24.0, 5.3, 22.0, 18.0, 21.0, "新能源"),
        ("601318", "中国平安", 4.9, 8.4, 1.1, 12.0, 7.0, 9.0, "金融"),
        ("600036", "招商银行", 4.3, 6.8, 0.9, 15.0, 5.0, 6.0, "金融"),
        ("600276", "恒瑞医药", 3.8, 42.0, 6.1, 16.0, 11.0, 13.0, "医药"),
    ],
    "510050": [
        ("600519", "贵州茅台", 9.0, 29.0, 9.6, 33.0, 15.0, 18.0, "消费"),
        ("601318", "中国平安", 8.5, 8.4, 1.1, 12.0, 7.0, 9.0, "金融"),
        ("600036", "招商银行", 7.4, 6.8, 0.9, 15.0, 5.0, 6.0, "金融"),
        ("601288", "农业银行", 6.2, 5.5, 0.7, 11.0, 3.0, 4.0, "金融"),
        ("601398", "工商银行", 6.1, 5.2, 0.7, 10.0, 3.0, 4.0, "金融"),
    ],
    "159915": [
        ("300750", "宁德时代", 10.0, 24.0, 5.3, 22.0, 18.0, 21.0, "新能源"),
        ("300760", "迈瑞医疗", 7.0, 29.0, 7.2, 29.0, 14.0, 16.0, "医药"),
        ("300059", "东方财富", 5.8, 24.0, 3.8, 15.0, 9.0, 10.0, "金融科技"),
        ("300124", "汇川技术", 4.9, 31.0, 7.4, 24.0, 17.0, 18.0, "工业"),
        ("300274", "阳光电源", 4.5, 18.0, 4.2, 21.0, 22.0, 20.0, "新能源"),
    ],
    "512100": [
        ("002384", "东山精密", 4.1, 21.0, 2.5, 13.0, 16.0, 17.0, "电子"),
        ("002463", "沪电股份", 3.9, 25.0, 4.1, 18.0, 17.0, 19.0, "电子"),
        ("300476", "胜宏科技", 3.6, 32.0, 5.4, 17.0, 20.0, 24.0, "电子"),
        ("603501", "韦尔股份", 3.5, 34.0, 4.5, 12.0, 18.0, 16.0, "半导体"),
        ("000977", "浪潮信息", 3.1, 27.0, 5.2, 14.0, 15.0, 14.0, "计算机"),
    ],
    "515880": [
        ("000063", "中兴通讯", 8.4, 17.0, 2.2, 14.0, 10.0, 11.0, "通信"),
        ("600941", "中国移动", 7.5, 16.0, 1.5, 10.0, 7.0, 7.0, "通信"),
        ("600050", "中国联通", 6.2, 18.0, 1.4, 8.0, 9.0, 10.0, "通信"),
        ("300394", "天孚通信", 5.6, 38.0, 8.2, 23.0, 28.0, 29.0, "通信"),
        ("300502", "新易盛", 5.2, 41.0, 9.1, 25.0, 31.0, 34.0, "通信"),
    ],
}


def trading_days(days: int = 90) -> list[date]:
    current = date.today()
    output: list[date] = []
    while len(output) < days:
        if current.weekday() < 5:
            output.append(current)
        current -= timedelta(days=1)
    return list(reversed(output))


def seed_database() -> None:
    with session_scope() as session:
        user_exists = session.scalar(select(User).limit(1))
        if user_exists:
            return

        session.add(User(id="demo-user", username="demo", display_name="演示用户"))

        for item in ETF_DATA:
            session.add(
                ETFMaster(
                    code=item["code"],
                    name=item["name"],
                    category=item["category"],
                    theme=item["theme"],
                    benchmark=item["benchmark"],
                    risk_level=item["risk_level"],
                    description=item["description"],
                )
            )

        session.flush()
        dates = trading_days(100)

        for item in ETF_DATA:
            rnd = random.Random(item["code"])
            prev_close = item["base_price"]
            for index, trade_day in enumerate(dates):
                cycle = math.sin(index / 8) * 0.0025
                shock = rnd.uniform(-item["volatility"], item["volatility"])
                daily_return = item["drift"] + cycle + shock
                close_price = max(0.8, prev_close * (1 + daily_return))
                open_price = prev_close * (1 + rnd.uniform(-0.006, 0.006))
                high_price = max(open_price, close_price) * (1 + rnd.uniform(0.001, 0.012))
                low_price = min(open_price, close_price) * (1 - rnd.uniform(0.001, 0.012))
                volume = 8000000 + rnd.uniform(-1800000, 2400000) + index * 2500
                turnover = volume * close_price
                session.add(
                    ETFQuote(
                        etf_code=item["code"],
                        trade_date=trade_day,
                        open_price=round(open_price, 4),
                        high_price=round(high_price, 4),
                        low_price=round(low_price, 4),
                        close_price=round(close_price, 4),
                        volume=round(volume, 2),
                        turnover=round(turnover, 2),
                        pct_change=round((close_price / prev_close - 1) * 100, 2),
                    )
                )
                prev_close = close_price

            latest_day = dates[-1]
            factor = item["factor"]
            session.add(
                ETFFactor(
                    etf_code=item["code"],
                    as_of=latest_day,
                    momentum=factor["momentum"],
                    volatility=factor["volatility"],
                    liquidity=factor["liquidity"],
                    money_flow=factor["money_flow"],
                    valuation=factor["valuation"],
                    industry_rotation=factor["industry_rotation"],
                    composite_score=factor["composite"],
                )
            )

            for constituent in CONSTITUENTS[item["code"]]:
                session.add(
                    ETFConstituent(
                        etf_code=item["code"],
                        stock_code=constituent[0],
                        stock_name=constituent[1],
                        weight=constituent[2],
                        pe=constituent[3],
                        pb=constituent[4],
                        roe=constituent[5],
                        revenue_growth=constituent[6],
                        profit_growth=constituent[7],
                        sector=constituent[8],
                    )
                )

            news_items = [
                (
                    f"{item['theme']}方向成交活跃，资金关注度抬升",
                    "财联社",
                    item["news_bias"] + 0.15,
                    "ETF 对应主题近期成交额放大，板块活跃度上升，短期情绪偏积极。",
                ),
                (
                    f"{item['name']}跟踪指数成分股一季报预告分化",
                    "证券时报",
                    item["news_bias"] - 0.03,
                    "部分权重股盈利超预期，但也存在景气分化，需关注业绩兑现节奏。",
                ),
                (
                    f"{item['theme']}相关政策持续推进，估值修复预期升温",
                    "东方财富",
                    item["news_bias"] + 0.08,
                    "政策与行业催化增强中期配置逻辑，不过高弹性品种仍需防范波动。",
                ),
            ]

            for offset, news_item in enumerate(news_items):
                session.add(
                    ETFNews(
                        etf_code=item["code"],
                        title=news_item[0],
                        source=news_item[1],
                        published_at=datetime.utcnow() - timedelta(hours=offset * 8 + rnd.randint(2, 6)),
                        sentiment=round(max(-1, min(1, news_item[2])), 2),
                        summary=news_item[3],
                    )
                )

        default_answers = {
            "age_range": "26-35",
            "investment_experience": "1-3年",
            "risk_tolerance": "可接受10%-15%回撤",
            "investment_goal": "稳健增值",
            "holding_period": "中期",
            "sector_preference": "宽基",
            "liquidity_need": "中等",
        }
        session.add(
            RiskQuestionnaireSubmission(
                user_id="demo-user",
                answers_json=str(default_answers),
                total_score=63,
                risk_level="平衡型",
                preference_tags="宽基,红利,中期配置",
                investment_horizon="中期",
                max_drawdown="10%-15%",
                summary="具备一定风险承受能力，适合以宽基和低波动行业 ETF 为核心进行中期配置。",
            )
        )
