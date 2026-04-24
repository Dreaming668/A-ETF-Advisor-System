from __future__ import annotations

import html
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urljoin, urlparse

from .etf_universe_provider import FUND_COMPANY_SUFFIXES
from .http_client import build_session
from .llm_provider import resolve_provider


SOURCE_PRIORITY = {
    "东方财富": 0.98,
    "新浪财经": 0.94,
    "证券时报": 0.92,
    "同花顺财经": 0.9,
    "财联社": 1.0,
}

POSITIVE_WORDS = ["上涨", "利好", "回暖", "突破", "增长", "景气", "修复", "增持", "活跃", "改善"]
NEGATIVE_WORDS = ["下跌", "利空", "承压", "回撤", "收缩", "波动", "风险", "减持", "拖累", "分化"]

ALLOWED_HOSTS = {
    "finance.eastmoney.com",
    "finance.sina.com.cn",
    "stock.10jqka.com.cn",
    "www.stcn.com",
    "www.cls.cn",
}

DOMESTIC_SOURCE_PAGES = [
    {"source": "东方财富", "url": "https://finance.eastmoney.com/", "referer": "https://finance.eastmoney.com/"},
    {"source": "新浪财经", "url": "https://finance.sina.com.cn/roll/", "referer": "https://finance.sina.com.cn/"},
    {"source": "同花顺财经", "url": "https://stock.10jqka.com.cn/", "referer": "https://stock.10jqka.com.cn/"},
    {"source": "证券时报", "url": "https://www.stcn.com/", "referer": "https://www.stcn.com/"},
    {"source": "财联社", "url": "https://www.cls.cn/", "referer": "https://www.cls.cn/"},
]

GENERIC_REJECT_TERMS = [
    "链接",
    "发起式",
    "净值",
    "估值",
    "行情走势",
    "怎么买ETF",
    "怎么购买ETF",
    "股吧",
    "论坛",
    "基金吧",
    "开户",
    "教程",
    "QDII",
    "LOF",
]

ARTICLE_PATH_REJECT_TERMS = ["guba", "fund", "jjjz", "howbuy", "caifuguba"]

GENERIC_WORDS = {"核心资产", "主题", "ETF", "成长", "指数", "中期配置", "宽基", "蓝筹", "行业"}

TOPIC_HINTS = {
    "消费电子": ["消费电子", "苹果产业链", "电子", "半导体", "芯片"],
    "新能源车": ["新能源车", "锂电", "电池", "汽车", "储能"],
    "新能源": ["新能源", "光伏", "风电", "锂电", "储能"],
    "光伏": ["光伏", "硅料", "组件", "逆变器", "新能源"],
    "电池": ["电池", "锂电", "储能", "新能源车"],
    "工程机械": ["工程机械", "机械", "装备", "基建", "挖机"],
    "高端装备": ["高端装备", "装备", "机械", "机器人", "制造业"],
    "通信": ["通信", "算力", "光模块", "运营商", "AI"],
    "通信设备": ["通信设备", "通信", "光模块", "算力"],
    "人工智能": ["人工智能", "AI", "算力", "大模型", "服务器"],
    "半导体": ["半导体", "芯片", "算力", "AI"],
    "芯片": ["芯片", "半导体", "算力", "AI"],
    "新材料": ["新材料", "材料", "有色", "化工", "稀土"],
    "有色": ["有色", "铜", "铝", "黄金", "稀土"],
    "化工": ["化工", "材料", "涨价", "周期"],
    "医药": ["医药", "创新药", "医疗", "生物"],
    "军工": ["军工", "国防", "航空", "航天"],
    "环保": ["环保", "碳中和", "水务", "固废"],
    "创业板": ["创业板", "成长", "科技"],
    "科创50": ["科创50", "科创", "半导体", "创新药"],
    "沪深300": ["沪深300", "A股", "核心资产", "蓝筹"],
    "上证50": ["上证50", "蓝筹", "央国企", "银行"],
    "中证1000": ["中证1000", "中小盘", "成长", "题材"],
    "中证500": ["中证500", "中盘", "成长", "A股"],
    "红利": ["红利", "高股息", "央国企", "低波"],
}


@dataclass
class NewsItem:
    title: str
    source: str
    published_at: datetime
    sentiment: float
    summary: str
    relevance: float = 0.0


@dataclass
class NewsCandidate:
    title: str
    source: str
    url: str
    published_at: datetime
    summary: str
    relevance: float


class DomesticFinanceNewsProvider:
    name = "cn_finance_portals"

    def __init__(self):
        self.session = build_session()

    def fetch_news(self, etf: dict[str, Any], limit: int = 8) -> list[NewsItem]:
        profile = self._build_profile(etf)
        candidates: list[NewsCandidate] = []
        seen_urls: set[str] = set()

        def append_candidates(items: list[NewsCandidate]) -> None:
            for candidate in items:
                if not candidate.url or candidate.url in seen_urls:
                    continue
                seen_urls.add(candidate.url)
                candidates.append(candidate)

        for page in DOMESTIC_SOURCE_PAGES:
            try:
                html_text = self._fetch_html(page["url"], referer=page["referer"])
            except Exception:
                continue
            append_candidates(self._extract_candidates(html_text, page["url"], page["source"], profile))

        if len(candidates) < max(limit * 3, 12):
            for page in DOMESTIC_SOURCE_PAGES:
                try:
                    html_text = self._fetch_html(page["url"], referer=page["referer"])
                except Exception:
                    continue
                append_candidates(self._extract_relaxed_candidates(html_text, page["url"], page["source"], profile))

        ranked = sorted(candidates, key=lambda item: item.relevance, reverse=True)
        enriched = self._build_enriched_candidates(ranked, profile, limit)

        if not enriched:
            raise RuntimeError(f"Domestic finance providers returned no relevant items for {etf['name']}")

        llm_selected = self._select_with_llm(etf, enriched, limit)
        if llm_selected:
            llm_selected.sort(key=lambda item: (item.relevance, item.published_at), reverse=True)
            return llm_selected[:limit]

        selected = self._select_with_rules(enriched, limit)
        if not selected:
            raise RuntimeError(f"Domestic finance providers returned no relevant items for {etf['name']}")
        selected.sort(key=lambda item: (item.relevance, item.published_at), reverse=True)
        return selected[:limit]

    def _build_enriched_candidates(
        self,
        ranked: list[NewsCandidate],
        profile: dict[str, Any],
        limit: int,
    ) -> list[NewsItem]:
        enriched: list[NewsItem] = []
        seen_titles: set[str] = set()

        for index, candidate in enumerate(ranked[: max(limit * 12, 96)]):
            published_at, summary = self._fetch_article_detail(candidate)
            title = self._normalize_title(candidate.title)
            if not title or title in seen_titles:
                continue

            relevance = max(
                candidate.relevance,
                self._score_relevance(title, summary, profile, candidate.source),
                self._score_fallback_relevance(title, summary, profile, candidate.source),
            )
            if relevance < 0.03:
                continue

            seen_titles.add(title)
            enriched.append(
                NewsItem(
                    title=title,
                    source=candidate.source,
                    published_at=published_at or datetime.utcnow() - timedelta(minutes=index * 3),
                    sentiment=self._score_sentiment(f"{title} {summary}"),
                    summary=self._normalize_summary(summary or title),
                    relevance=relevance,
                )
            )
        return enriched

    def _select_with_rules(self, enriched: list[NewsItem], limit: int) -> list[NewsItem]:
        selected = [item for item in enriched if item.relevance >= 0.28][:limit]
        if len(selected) >= limit:
            return selected

        for item in enriched:
            if item in selected or item.relevance < 0.12:
                continue
            selected.append(item)
            if len(selected) >= limit:
                return selected

        for item in enriched:
            if item in selected or item.relevance < 0.06:
                continue
            selected.append(item)
            if len(selected) >= limit:
                return selected
        return selected

    def _select_with_llm(self, etf: dict[str, Any], enriched: list[NewsItem], limit: int) -> list[NewsItem]:
        try:
            provider = resolve_provider("auto")
        except Exception:
            return []

        llm_pool = enriched[: max(limit * 6, 36)]
        default = {"selected": []}
        user_prompt = "\n".join(
            [
                f"ETF名称: {etf.get('name') or ''}",
                f"ETF代码: {etf.get('code') or ''}",
                f"跟踪基准: {etf.get('benchmark') or ''}",
                f"主题: {etf.get('theme') or ''}",
                f"分类: {etf.get('category') or ''}",
                f"目标: 从候选新闻里挑出最多 {limit} 条与该 ETF 有一定相关性的真实财经新闻，并按相关性从高到低排序。",
                "放宽标准: 只要与 ETF 对应的主题、行业、产业链、板块、赛道、基准指数或 A 股市场有一点相关，就可以保留。",
                "候选新闻列表:",
                *[
                    (
                        f"{idx + 1}. 标题: {item.title}\n"
                        f"来源: {item.source}\n"
                        f"时间: {item.published_at.isoformat(timespec='seconds')}\n"
                        f"摘要: {item.summary}\n"
                        f"规则分: {item.relevance:.3f}"
                    )
                    for idx, item in enumerate(llm_pool)
                ],
                (
                    "请严格输出 JSON 对象，格式为 "
                    '{"selected":[{"id":1,"relevance":0.86},{"id":3,"relevance":0.64}]}. '
                    "id 必须来自候选序号，relevance 取 0 到 1。不要编造新闻，不要输出候选列表以外的内容。"
                ),
            ]
        )
        developer_prompt = (
            "你是中文 ETF 新闻筛选器。你只能根据给定候选新闻进行筛选和排序，不能编造任何新闻。"
            "优先保留与 ETF 主题、行业、成分方向、基准指数或市场风格有关系的新闻。"
            "如果缺少完全精准的新闻，只要有轻度相关性也应保留。"
            "如果明显无关，才不要选。输出必须是 JSON object。"
        )
        try:
            result = provider.generate_json(developer_prompt, user_prompt, default)
        except Exception:
            return []

        selected_items: list[NewsItem] = []
        seen_ids: set[int] = set()
        raw_selected = result.get("selected")
        if not isinstance(raw_selected, list):
            return []

        for row in raw_selected:
            if not isinstance(row, dict):
                continue
            try:
                idx = int(row.get("id"))
            except Exception:
                continue
            if idx < 1 or idx > len(llm_pool) or idx in seen_ids:
                continue
            seen_ids.add(idx)
            item = llm_pool[idx - 1]
            try:
                llm_relevance = float(row.get("relevance", item.relevance))
            except Exception:
                llm_relevance = item.relevance
            selected_items.append(
                NewsItem(
                    title=item.title,
                    source=item.source,
                    published_at=item.published_at,
                    sentiment=item.sentiment,
                    summary=item.summary,
                    relevance=max(0.0, min(1.0, llm_relevance)),
                )
            )
            if len(selected_items) >= limit:
                break
        return selected_items

    def _build_profile(self, etf: dict[str, Any]) -> dict[str, Any]:
        name = str(etf.get("name") or "").strip()
        benchmark = str(etf.get("benchmark") or "").strip()
        theme = str(etf.get("theme") or "").strip()
        category = str(etf.get("category") or "").strip()

        normalized_name_terms = self._normalize_etf_name(name)
        normalized_benchmark_terms = self._normalize_benchmark(benchmark)
        hint_terms = self._topic_hints(name, theme, benchmark)
        raw_terms = [name, benchmark, theme, *normalized_name_terms, *normalized_benchmark_terms, *hint_terms]

        anchor_terms: list[str] = []
        soft_terms: list[str] = []
        for term in raw_terms:
            anchor_terms.extend(self._expand_term(term))
            soft_terms.extend(self._split_term(term))

        anchor_terms = self._dedupe_terms(anchor_terms)
        soft_terms = self._dedupe_terms(item for item in soft_terms if item not in anchor_terms)
        target_code = str(etf.get("code") or "").strip()
        core_terms = self._dedupe_terms([*normalized_name_terms, *normalized_benchmark_terms, theme, *hint_terms])
        fallback_terms = self._build_fallback_terms(name, benchmark, theme, category, anchor_terms, soft_terms)

        return {
            "target_code": target_code,
            "anchor_terms": anchor_terms,
            "soft_terms": soft_terms,
            "core_terms": core_terms,
            "fallback_terms": fallback_terms,
        }

    def _fetch_html(self, url: str, referer: str | None = None) -> str:
        headers = {"Referer": referer or url}
        response = self.session.get(url, timeout=12, headers=headers)
        response.raise_for_status()
        response.encoding = response.apparent_encoding or response.encoding or "utf-8"
        return response.text

    def _extract_candidates(
        self,
        html_text: str,
        base_url: str,
        default_source: str,
        profile: dict[str, Any],
    ) -> list[NewsCandidate]:
        results: list[NewsCandidate] = []
        seen: set[str] = set()

        for match in re.finditer(r"<a[^>]+href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", html_text, re.I | re.S):
            raw_href, raw_title = match.groups()
            title = self._clean_text(raw_title)
            href = self._normalize_url(raw_href, base_url)
            if not title or not href or href in seen:
                continue
            if not self._is_allowed_article(href):
                continue
            if len(title) < 6 or len(title) > 60:
                continue
            if not self._might_be_relevant(title, profile):
                continue

            preliminary_score = self._score_relevance(title, "", profile, default_source)
            if preliminary_score < 0.1:
                continue

            seen.add(href)
            results.append(
                NewsCandidate(
                    title=title,
                    source=self._guess_source(href) or default_source,
                    url=href,
                    published_at=datetime.utcnow(),
                    summary=title,
                    relevance=preliminary_score,
                )
            )
        return results

    def _extract_relaxed_candidates(
        self,
        html_text: str,
        base_url: str,
        default_source: str,
        profile: dict[str, Any],
    ) -> list[NewsCandidate]:
        results: list[NewsCandidate] = []
        seen: set[str] = set()

        for match in re.finditer(r"<a[^>]+href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", html_text, re.I | re.S):
            raw_href, raw_title = match.groups()
            title = self._clean_text(raw_title)
            href = self._normalize_url(raw_href, base_url)
            if not title or not href or href in seen:
                continue
            if not self._is_allowed_article(href):
                continue
            if len(title) < 6 or len(title) > 60:
                continue

            preliminary_score = self._score_fallback_relevance(title, "", profile, default_source)
            if preliminary_score < 0.03:
                continue

            seen.add(href)
            results.append(
                NewsCandidate(
                    title=title,
                    source=self._guess_source(href) or default_source,
                    url=href,
                    published_at=datetime.utcnow(),
                    summary=title,
                    relevance=preliminary_score,
                )
            )
        return results

    def _might_be_relevant(self, title: str, profile: dict[str, Any]) -> bool:
        if self._contains_hard_reject(title, profile):
            return False
        hard_hits = sum(1 for term in profile["anchor_terms"] if term and term in title)
        soft_hits = sum(1 for term in profile["soft_terms"] if term and term in title)
        core_hits = sum(1 for term in profile.get("core_terms", []) if term and term in title)
        fallback_hits = sum(1 for term in profile.get("fallback_terms", []) if term and term in title)
        return hard_hits > 0 or core_hits > 0 or soft_hits > 0 or fallback_hits > 0 or (
            bool(profile.get("target_code")) and profile["target_code"] in title
        )

    def _build_fallback_terms(
        self,
        name: str,
        benchmark: str,
        theme: str,
        category: str,
        anchor_terms: list[str],
        soft_terms: list[str],
    ) -> list[str]:
        text = " ".join([name, benchmark, theme, category])
        terms: list[str] = []

        if any(token in text for token in ["沪深300", "上证50", "中证1000", "宽基", "核心资产", "大盘"]):
            terms.extend(["A股", "指数", "大盘", "市场", "板块", "中国资产", "A50"])
        if "创业板" in text:
            terms.extend(["创业板", "成长", "科技", "AI", "算力"])
        if "通信" in text:
            terms.extend(["通信", "算力", "运营商", "光模块", "AI"])
        if "中证1000" in text:
            terms.extend(["中小盘", "题材", "成长", "指数", "A股"])
        if "消费电子" in text:
            terms.extend(["消费电子", "苹果", "果链", "电子", "半导体", "芯片"])
        if "工程机械" in text or "机械" in text:
            terms.extend(["工程机械", "机械", "装备", "基建", "制造业", "挖机"])
        if "材料" in text:
            terms.extend(["新材料", "材料", "有色", "化工", "稀土"])
        if "半导体" in text or "芯片" in text:
            terms.extend(["半导体", "芯片", "算力", "AI"])
        if "人工智能" in text or "AI" in text:
            terms.extend(["人工智能", "AI", "算力", "服务器"])
        if "医药" in text or "医疗" in text:
            terms.extend(["医药", "创新药", "医疗", "生物"])
        if "军工" in text:
            terms.extend(["军工", "国防", "航空", "航天"])
        if "环保" in text:
            terms.extend(["环保", "碳中和", "水务", "固废"])
        if theme or category:
            terms.extend(["板块", "行业", "产业", "赛道"])
        if not terms:
            terms.extend(anchor_terms[:2])
            terms.extend(soft_terms[:5])

        return self._dedupe_terms(terms)

    def _topic_hints(self, *values: str) -> list[str]:
        text = "".join(values)
        terms: list[str] = []
        for key, hints in TOPIC_HINTS.items():
            if key in text:
                terms.extend(hints)
        return self._dedupe_terms(terms)

    @staticmethod
    def _clean_text(value: str) -> str:
        value = re.sub(r"<script.*?</script>", " ", value or "", flags=re.I | re.S)
        value = re.sub(r"<style.*?</style>", " ", value, flags=re.I | re.S)
        value = re.sub(r"<!--.*?-->", " ", value, flags=re.I | re.S)
        value = re.sub(r"<[^>]+>", " ", value)
        value = html.unescape(value)
        value = re.sub(r"\s+", " ", value)
        return value.strip(" -|")

    @staticmethod
    def _normalize_url(href: str, base_url: str) -> str:
        href = html.unescape((href or "").strip())
        if not href or href.startswith("javascript:") or href.startswith("#"):
            return ""
        return urljoin(base_url, href)

    def _is_allowed_article(self, url: str) -> bool:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            return False
        if parsed.netloc not in ALLOWED_HOSTS:
            return False
        path = parsed.path.lower()
        if any(term in path for term in ARTICLE_PATH_REJECT_TERMS):
            return False
        return "/a/" in path or path.endswith(".shtml") or path.endswith(".html")

    def _guess_source(self, url: str) -> str:
        host = urlparse(url).netloc
        for page in DOMESTIC_SOURCE_PAGES:
            if urlparse(page["url"]).netloc == host:
                return str(page["source"])
        return ""

    def _fetch_article_detail(self, candidate: NewsCandidate) -> tuple[datetime, str]:
        try:
            html_text = self._fetch_html(candidate.url, referer=candidate.url)
            published_at = self._extract_publish_time(html_text) or candidate.published_at
            summary = self._extract_summary(html_text, candidate.title) or candidate.summary
            return published_at, summary
        except Exception:
            return candidate.published_at, candidate.summary

    def _extract_publish_time(self, html_text: str) -> datetime | None:
        patterns = [
            (r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", "%Y-%m-%d %H:%M:%S"),
            (r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2})", "%Y-%m-%d %H:%M"),
            (r"(\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2})", "%Y/%m/%d %H:%M:%S"),
            (r"(\d{4}/\d{2}/\d{2} \d{2}:\d{2})", "%Y/%m/%d %H:%M"),
            (r"(\d{4}年\d{2}月\d{2}日\s*\d{2}:\d{2})", "%Y年%m月%d日 %H:%M"),
        ]
        for pattern, fmt in patterns:
            match = re.search(pattern, html_text)
            if not match:
                continue
            value = re.sub(r"\s+", " ", match.group(1)).strip()
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                continue
        return None

    def _extract_summary(self, html_text: str, fallback_title: str) -> str:
        meta_patterns = [
            r"<meta[^>]+name=[\"']description[\"'][^>]+content=[\"']([^\"']+)[\"']",
            r"<meta[^>]+property=[\"']og:description[\"'][^>]+content=[\"']([^\"']+)[\"']",
        ]
        for pattern in meta_patterns:
            match = re.search(pattern, html_text, re.I)
            if not match:
                continue
            summary = self._clean_text(match.group(1))
            if summary:
                return summary[:180]

        paragraphs: list[str] = []
        for match in re.finditer(r"<p[^>]*>(.*?)</p>", html_text, re.I | re.S):
            paragraph = self._clean_text(match.group(1))
            if len(paragraph) >= 18 and paragraph != fallback_title:
                paragraphs.append(paragraph)
            if len(paragraphs) >= 3:
                break
        if paragraphs:
            return " ".join(paragraphs)[:180]
        return fallback_title[:180]

    def _expand_term(self, value: str) -> list[str]:
        value = re.sub(r"\s+", "", value or "")
        if not value:
            return []

        terms = [value]
        terms.extend(self._normalize_etf_name(value))
        terms.extend(self._normalize_benchmark(value))

        stripped = value
        stripped = re.sub(r"(发起式联接[ABC]?|联接[ABC]?|联接)$", "", stripped)
        stripped = re.sub(r"(ETF|指数|主题)$", "", stripped, flags=re.I)
        stripped = stripped.replace("中证全指", "")
        if stripped and stripped != value:
            terms.append(stripped)

        for token in ("沪深300", "上证50", "中证1000", "创业板", "科创50", "消费电子", "新能源", "通信", "红利"):
            if token in value:
                terms.append(token)
        return self._dedupe_terms(terms)

    def _split_term(self, value: str) -> list[str]:
        cleaned = re.sub(r"[^\u4e00-\u9fff0-9A-Za-z]+", " ", value or "").strip()
        if not cleaned:
            return []

        pieces: list[str] = []
        for item in cleaned.split():
            item = re.sub(r"(ETF|指数|主题)$", "", item, flags=re.I)
            if len(item) >= 2 and item not in GENERIC_WORDS:
                pieces.append(item)
            if len(item) < 4:
                continue
            for token in (
                "创业板",
                "沪深300",
                "上证50",
                "中证1000",
                "通信设备",
                "通信",
                "算力",
                "科技",
                "消费电子",
                "新能源",
                "红利",
                "半导体",
                "人工智能",
                "工程机械",
                "新材料",
                "高端装备",
                "军工",
                "医药",
                "环保",
            ):
                if token in item and token not in pieces:
                    pieces.append(token)
        return pieces

    def _normalize_etf_name(self, value: str) -> list[str]:
        value = re.sub(r"\s+", "", value or "")
        if not value:
            return []

        terms = [value]
        stripped_company = self._strip_company_suffix(value)
        if stripped_company and stripped_company != value:
            terms.append(stripped_company)

        etf_match = re.search(r"ETF", stripped_company, re.I)
        if etf_match:
            head = stripped_company[: etf_match.end()]
            core = stripped_company[: etf_match.start()]
            if head:
                terms.append(head)
            if core:
                terms.append(core)

        core = re.sub(r"(发起式联接[ABC]?|联接[ABC]?|联接)$", "", stripped_company)
        core = re.sub(r"(ETF|指数|主题)$", "", core, flags=re.I)
        core = core.replace("中证全指", "")
        if core:
            terms.append(core)
            if "ETF" not in core:
                terms.append(f"{core}ETF")
        return self._dedupe_terms(terms)

    def _normalize_benchmark(self, value: str) -> list[str]:
        value = re.sub(r"\s+", "", value or "")
        if not value:
            return []

        terms = [value]
        stripped = value.replace("中证全指", "")
        stripped = re.sub(r"(指数|主题)$", "", stripped)
        if stripped:
            terms.append(stripped)
            if "ETF" not in stripped:
                terms.append(f"{stripped}ETF")
        return self._dedupe_terms(terms)

    @staticmethod
    def _strip_company_suffix(value: str) -> str:
        cleaned = value
        for suffix in sorted(FUND_COMPANY_SUFFIXES, key=len, reverse=True):
            if cleaned.endswith(suffix):
                cleaned = cleaned.removesuffix(suffix).strip()
                break
        return cleaned

    def _dedupe_terms(self, items) -> list[str]:
        results: list[str] = []
        seen: set[str] = set()
        for item in items:
            value = str(item or "").strip()
            if len(value) < 2 or value in GENERIC_WORDS or value in seen:
                continue
            seen.add(value)
            results.append(value)
        return sorted(results, key=len, reverse=True)

    def _contains_hard_reject(self, text: str, profile: dict[str, Any]) -> bool:
        normalized = text.upper()
        if any(term.upper() in normalized for term in GENERIC_REJECT_TERMS):
            return True

        other_fund_codes = re.findall(r"\((\d{6})\)", text)
        if other_fund_codes and profile["target_code"] not in other_fund_codes:
            return True

        soft_hits = sum(1 for term in profile.get("soft_terms", []) if term and term in text)
        fallback_hits = sum(1 for term in profile.get("fallback_terms", []) if term and term in text)
        core_hits = sum(1 for term in profile.get("core_terms", []) if term and term in text)
        if "ETF" in normalized and not (
            any(term in text for term in profile["anchor_terms"])
            or core_hits > 0
            or fallback_hits > 0
            or soft_hits > 0
            or (profile.get("target_code") and profile["target_code"] in text)
        ):
            return True

        return False

    def _score_relevance(self, title: str, summary: str, profile: dict[str, Any], source: str) -> float:
        text = f"{title} {summary}"
        if self._contains_hard_reject(text, profile):
            return 0.0

        title_hits = sum(1 for term in profile["anchor_terms"] if term and term in title)
        body_hits = sum(1 for term in profile["anchor_terms"] if term and term in summary)
        soft_hits = sum(1 for term in profile["soft_terms"] if term and term in text)
        core_hits = sum(1 for term in profile.get("core_terms", []) if term and term in text)
        fallback_hits = sum(1 for term in profile.get("fallback_terms", []) if term and term in text)
        source_boost = SOURCE_PRIORITY.get(source, 0.82)

        score = 0.04 + source_boost * 0.12
        score += min(title_hits, 2) * 0.2
        score += min(body_hits, 2) * 0.13
        score += min(core_hits, 3) * 0.11
        score += min(soft_hits, 4) * 0.08
        score += min(fallback_hits, 5) * 0.07
        if profile["target_code"] and profile["target_code"] in text:
            score += 0.22
        if "ETF" in title.upper() and (title_hits > 0 or core_hits > 0 or fallback_hits > 0):
            score += 0.06
        if title_hits == 0 and body_hits == 0 and core_hits == 0 and fallback_hits == 0 and soft_hits == 0:
            score -= 0.08
        return max(0.0, min(1.0, score))

    def _score_fallback_relevance(self, title: str, summary: str, profile: dict[str, Any], source: str) -> float:
        text = f"{title} {summary}"
        if self._contains_hard_reject(text, profile):
            return 0.0

        anchor_hits = sum(1 for term in profile["anchor_terms"] if term and term in text)
        core_hits = sum(1 for term in profile.get("core_terms", []) if term and term in text)
        soft_hits = sum(1 for term in profile["soft_terms"] if term and term in text)
        fallback_title_hits = sum(1 for term in profile["fallback_terms"] if term and term in title)
        fallback_text_hits = sum(1 for term in profile["fallback_terms"] if term and term in text)

        score = 0.01 + SOURCE_PRIORITY.get(source, 0.82) * 0.06
        score += min(anchor_hits, 2) * 0.08
        score += min(core_hits, 3) * 0.08
        score += min(soft_hits, 4) * 0.07
        score += min(fallback_title_hits, 4) * 0.1
        score += min(fallback_text_hits, 5) * 0.08
        if profile["target_code"] and profile["target_code"] in text:
            score += 0.1
        if anchor_hits == 0 and core_hits == 0 and soft_hits == 0 and fallback_text_hits == 0:
            score -= 0.06
        return max(0.0, min(1.0, score))

    @staticmethod
    def _normalize_title(title: str) -> str:
        title = re.sub(r"\s+", " ", title)
        return title.strip(" -|")

    @staticmethod
    def _normalize_summary(summary: str) -> str:
        summary = re.sub(r"\s+", " ", summary).strip()
        return summary[:120]

    @staticmethod
    def _score_sentiment(text: str) -> float:
        score = 0
        for word in POSITIVE_WORDS:
            if word in text:
                score += 1
        for word in NEGATIVE_WORDS:
            if word in text:
                score -= 1
        return max(-1.0, min(1.0, score / 4))


class NewsSummaryService:
    def summarize(self, etf: dict[str, Any], items: list[NewsItem], preferred_provider: str = "auto") -> list[NewsItem]:
        provider = resolve_provider(preferred_provider)
        if provider is None or not items:
            return items

        raw_text = "\n".join(
            f"{idx + 1}. 标题: {item.title}\n来源: {item.source}\n原摘要: {item.summary}"
            for idx, item in enumerate(items)
        )
        default = {str(idx + 1): item.summary for idx, item in enumerate(items)}
        prompt = (
            f"请为 ETF {etf['name']} 的新闻列表生成更短、更适合投顾展示的中文摘要。"
            "输出 JSON，键为新闻序号，值为 20 到 50 字摘要，要求严谨、中性、不能编造。"
        )
        try:
            result = provider.generate_json(prompt, raw_text, default)
        except Exception:
            return items

        summarized: list[NewsItem] = []
        for idx, item in enumerate(items):
            summarized.append(
                NewsItem(
                    title=item.title,
                    source=item.source,
                    published_at=item.published_at,
                    sentiment=item.sentiment,
                    summary=str(result.get(str(idx + 1), item.summary)),
                    relevance=item.relevance,
                )
            )
        return summarized


def resolve_news_provider(preferred: str = "auto"):
    if preferred not in {"auto", "cn_finance_portals"}:
        raise ValueError(f"Unsupported news provider: {preferred}")
    return DomesticFinanceNewsProvider()


def news_provider_status() -> dict[str, Any]:
    providers = [
        {
            "name": "cn_finance_portals",
            "installed": True,
            "usable": True,
            "detail": "国内财经新闻聚合：东方财富/新浪财经/同花顺财经/证券时报/财联社，多轮关键词清洗和宽松召回提升 ETF 相关新闻命中率。",
        }
    ]
    return {"preferred": "cn_finance_portals", "providers": providers}
