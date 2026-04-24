from __future__ import annotations

import re
from dataclasses import dataclass

from .http_client import build_session


ETF_UNIVERSE_FS = "b:MK0021,b:MK0022,b:MK0023,b:MK0024"
FUND_COMPANY_SUFFIXES = [
    "华夏",
    "易方达",
    "嘉实",
    "博时",
    "富国",
    "华安",
    "汇添富",
    "南方",
    "广发",
    "国泰",
    "招商",
    "鹏华",
    "天弘",
    "银华",
    "工银瑞信",
    "华宝",
    "华泰柏瑞",
    "景顺长城",
    "兴业",
    "平安",
    "万家",
    "建信",
    "国联安",
    "大成",
    "中欧",
    "华富",
    "摩根",
    "华福",
    "中银",
    "创金合信",
    "永赢",
    "中金",
    "申万菱信",
    "汇安",
    "长盛",
    "新华",
    "鹏扬",
]


@dataclass
class ETFUniverseRecord:
    code: str
    name: str
    category: str
    theme: str
    benchmark: str
    risk_level: str
    description: str


class EastmoneyETFUniverseProvider:
    name = "eastmoney"

    def __init__(self):
        self.session = build_session()

    def fetch_all(self) -> list[ETFUniverseRecord]:
        records: dict[str, ETFUniverseRecord] = {}
        page = 1
        page_size = 100
        total = None

        while True:
            response = self.session.get(
                "https://push2.eastmoney.com/api/qt/clist/get",
                params={
                    "pn": str(page),
                    "pz": str(page_size),
                    "po": "1",
                    "np": "1",
                    "ut": "bd1d9ddb04089700cf9c27f6f7426281",
                    "fltt": "2",
                    "invt": "2",
                    "fid": "f3",
                    "fs": ETF_UNIVERSE_FS,
                    "fields": "f12,f13,f14",
                },
                timeout=20,
            )
            response.raise_for_status()
            payload = response.json()
            data = payload.get("data") or {}
            total = int(data.get("total") or 0)
            rows = data.get("diff") or []
            if not rows:
                break

            for row in rows:
                code = str(row.get("f12") or "").strip()
                name = str(row.get("f14") or "").strip()
                if not code or not name or len(code) != 6:
                    continue
                if code in records:
                    continue
                records[code] = self._build_record(code, name)

            if total and len(records) >= total:
                break
            if len(rows) < page_size:
                break
            page += 1

        if not records:
            raise RuntimeError("Eastmoney ETF universe returned empty data")
        return sorted(records.values(), key=lambda item: item.code)

    def _build_record(self, code: str, name: str) -> ETFUniverseRecord:
        theme = self._infer_theme(name)
        category = self._infer_category(name, theme)
        benchmark = self._infer_benchmark(theme)
        risk_level = self._infer_risk_level(category, theme)
        description = self._infer_description(category, theme, risk_level)
        return ETFUniverseRecord(
            code=code,
            name=name,
            category=category,
            theme=theme,
            benchmark=benchmark,
            risk_level=risk_level,
            description=description,
        )

    @staticmethod
    def _infer_theme(name: str) -> str:
        theme = re.sub(r"ETF.*$", "", name, flags=re.IGNORECASE).strip()
        for suffix in sorted(FUND_COMPANY_SUFFIXES, key=len, reverse=True):
            if theme.endswith(suffix):
                theme = theme.removesuffix(suffix).strip()
                break
        theme = re.sub(r"\s+", "", theme)
        return theme or name

    @staticmethod
    def _infer_category(name: str, theme: str) -> str:
        text = f"{name}{theme}"
        if any(keyword in text for keyword in ["货币", "现金管理"]):
            return "货币"
        if any(keyword in text for keyword in ["国债", "政金债", "信用债", "公司债", "城投债", "短融", "可转债", "债券", "同业存单"]):
            return "债券"
        if any(keyword in text for keyword in ["黄金", "原油", "油气", "天然气", "豆粕", "有色", "贵金属", "商品"]):
            return "商品"
        if any(keyword in text for keyword in ["恒生", "纳指", "纳斯达克", "标普", "日经", "法国", "德国", "亚太", "沙特", "巴西", "越南", "印度", "全球", "美国"]):
            return "跨境"
        if any(keyword in text for keyword in ["沪深300", "上证50", "中证500", "中证800", "中证1000", "科创", "科创50", "双创", "创业板", "深证", "沪深", "全指", "综指", "A50", "300", "500", "800", "1000"]):
            return "宽基"
        if any(keyword in text for keyword in ["红利", "央企", "国企", "价值", "低波", "消费", "金融", "银行"]):
            return "策略"
        return "行业"

    @staticmethod
    def _infer_benchmark(theme: str) -> str:
        if not theme:
            return "ETF跟踪指数"
        if theme.endswith("指数"):
            return theme
        if any(keyword in theme for keyword in ["黄金", "原油", "油气", "天然气", "豆粕", "有色", "商品"]):
            return f"{theme}相关标的"
        return f"{theme}指数"

    @staticmethod
    def _infer_risk_level(category: str, theme: str) -> str:
        if category == "货币":
            return "稳健型"
        if category == "债券":
            return "稳健型"
        if category == "商品":
            return "积极型"
        if category == "跨境":
            return "积极型"
        if category == "宽基":
            if any(keyword in theme for keyword in ["上证50", "沪深300", "A50", "红利", "低波"]):
                return "平衡型"
            if any(keyword in theme for keyword in ["创业板", "科创", "1000", "双创"]):
                return "积极型"
            return "平衡型"
        if category == "策略":
            return "平衡型"
        if any(keyword in theme for keyword in ["芯片", "半导体", "人工智能", "机器人", "游戏", "军工", "创新药", "新能源", "光伏"]):
            return "激进型"
        return "积极型"

    @staticmethod
    def _infer_description(category: str, theme: str, risk_level: str) -> str:
        if category == "货币":
            return f"跟踪{theme}类现金管理资产，波动通常较低，更适合做流动性管理与低风险配置。"
        if category == "债券":
            return f"聚焦{theme}方向，净值波动相对较低，适合稳健型资金做中短期配置与流动性管理。"
        if category == "商品":
            return f"跟踪{theme}相关商品资产，受全球定价与供需周期影响较大，配置时需关注波动放大。"
        if category == "跨境":
            return f"覆盖{theme}方向的跨境资产，受海外市场、汇率和全球风险偏好共同影响。"
        if category == "宽基":
            return f"围绕{theme}进行被动跟踪，适合作为 A 股核心资产配置工具，风险等级为{risk_level}。"
        if category == "策略":
            return f"聚焦{theme}策略因子，兼顾收益弹性与风格暴露，适合做风格增强配置。"
        return f"聚焦{theme}主题，行业景气、政策与资金偏好变化会更快传导到 ETF 波动。"
