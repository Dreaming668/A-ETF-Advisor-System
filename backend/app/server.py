from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs

from sqlalchemy import desc, or_, select

from .config import REPORT_DIR
from .database import init_db, session_scope
from .catalog import ETF_CATALOG
from .models import AnalysisReport, ChatMessage, ChatSession, ETFConstituent, ETFFactor, ETFMaster, ETFNews, ETFQuote, RiskQuestionnaireSubmission, User
from .bootstrap import bootstrap_database
from .services.analysis_engine import AnalysisService
from .services.chat_engine import ChatService
from .services.data_provider import provider_status as market_provider_status
from .services.etf_availability_service import effective_unsupported_etf_codes, load_unsupported_etf_codes, mark_etf_unsupported, unmark_etf_unsupported
from .services.llm_provider import provider_status as model_provider_status
from .services.news_provider import news_provider_status
from .services.news_sync_service import NewsSyncService
from .services.report_service import ReportService
from .services.risk_engine import RiskEngine
from .services.sync_service import SyncService

BASE_DIR = Path(__file__).resolve().parent
TEMPLATE_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"


def create_app():
    init_db()
    bootstrap_database()

    def app(environ, start_response):
        method = environ["REQUEST_METHOD"]
        path = environ.get("PATH_INFO", "/")

        if path == "/":
            return serve_file(start_response, TEMPLATE_DIR / "index.html", "text/html; charset=utf-8")
        if path.startswith("/static/"):
            rel = path.removeprefix("/static/")
            file_path = STATIC_DIR / rel
            content_type = "text/plain; charset=utf-8"
            if file_path.suffix == ".css":
                content_type = "text/css; charset=utf-8"
            elif file_path.suffix == ".js":
                content_type = "application/javascript; charset=utf-8"
            return serve_file(start_response, file_path, content_type)

        try:
            if path == "/api/health" and method == "GET":
                return json_response(start_response, {"status": "ok"})
            if path == "/api/bootstrap" and method == "GET":
                return handle_bootstrap(start_response)
            if path == "/api/system/data-sources" and method == "GET":
                return json_response(start_response, market_provider_status())
            if path == "/api/system/news-sources" and method == "GET":
                return json_response(start_response, news_provider_status())
            if path == "/api/system/model-providers" and method == "GET":
                return json_response(start_response, model_provider_status())
            if path == "/api/risk-assessments/latest" and method == "GET":
                params = get_query_params(environ)
                return handle_latest_risk(start_response, params.get("user_id", ["demo-user"])[0])
            if path == "/api/risk-assessments" and method == "POST":
                return handle_create_risk(start_response, get_json_body(environ))
            if path == "/api/etfs" and method == "GET":
                params = get_query_params(environ)
                return handle_list_etfs(
                    start_response,
                    params.get("query", [""])[0],
                    params.get("category", [""])[0],
                )
            if path.startswith("/api/etfs/") and path.endswith("/news/refresh") and method == "POST":
                etf_code = path.split("/")[-3]
                return handle_refresh_news(start_response, etf_code, get_json_body(environ))
            if path.startswith("/api/etfs/") and path.endswith("/fundamentals/refresh") and method == "POST":
                etf_code = path.split("/")[-3]
                return handle_refresh_fundamentals(start_response, etf_code, get_json_body(environ))
            if path.startswith("/api/etfs/") and path.endswith("/factors/refresh") and method == "POST":
                etf_code = path.split("/")[-3]
                return handle_refresh_factors(start_response, etf_code, get_json_body(environ))
            if path.startswith("/api/etfs/") and path.endswith("/quotes/refresh") and method == "POST":
                etf_code = path.split("/")[-3]
                return handle_refresh_quotes(start_response, etf_code, get_json_body(environ))
            if path.startswith("/api/etfs/") and path.endswith("/refresh") and method == "POST":
                etf_code = path.split("/")[-2]
                return handle_refresh_etf(start_response, etf_code, get_json_body(environ))
            if path.startswith("/api/etfs/") and method == "GET":
                etf_code = path.split("/")[-1]
                return handle_etf_detail(start_response, etf_code)
            if path == "/api/analysis/reports" and method == "POST":
                return handle_create_analysis(start_response, get_json_body(environ))
            if path == "/api/reports" and method == "GET":
                params = get_query_params(environ)
                return handle_list_reports(start_response, params.get("user_id", ["demo-user"])[0])
            if path.startswith("/api/reports/") and path.endswith("/download") and method == "GET":
                return handle_download_report(start_response, int(path.split("/")[-2]))
            if path.startswith("/api/reports/") and method == "DELETE":
                return handle_delete_report(start_response, int(path.split("/")[-1]))
            if path.startswith("/api/reports/") and method == "GET":
                return handle_report_detail(start_response, int(path.split("/")[-1]))
            if path == "/api/chat/sessions" and method == "POST":
                return handle_create_session(start_response, get_json_body(environ))
            if path.startswith("/api/chat/sessions/") and path.endswith("/messages") and method == "POST":
                return handle_send_message(start_response, int(path.split("/")[-2]), get_json_body(environ))
            if path.startswith("/api/chat/sessions/") and method == "GET":
                return handle_get_session(start_response, int(path.split("/")[-1]))
        except Exception as exc:
            return json_response(start_response, {"error": str(exc)}, status="500 Internal Server Error")

        return json_response(start_response, {"error": "Not found"}, status="404 Not Found")

    return app


def serve_file(start_response, file_path: Path, content_type: str):
    if not file_path.exists() or not file_path.is_file():
        return json_response(start_response, {"error": "Not found"}, status="404 Not Found")
    data = file_path.read_bytes()
    start_response("200 OK", [("Content-Type", content_type), ("Content-Length", str(len(data)))])
    return [data]


def get_query_params(environ):
    return parse_qs(environ.get("QUERY_STRING", ""), keep_blank_values=True)


def get_json_body(environ):
    try:
        length = int(environ.get("CONTENT_LENGTH") or 0)
    except ValueError:
        length = 0
    body = environ["wsgi.input"].read(length) if length else b"{}"
    return json.loads(body.decode("utf-8") or "{}")


def json_response(start_response, payload, status="200 OK"):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    start_response(status, [("Content-Type", "application/json; charset=utf-8"), ("Content-Length", str(len(body)))])
    return [body]


def html_response(start_response, html: str, status="200 OK", disposition: str | None = None):
    body = html.encode("utf-8")
    headers = [("Content-Type", "text/html; charset=utf-8"), ("Content-Length", str(len(body)))]
    if disposition:
        headers.append(("Content-Disposition", disposition))
    start_response(status, headers)
    return [body]


def serialize_risk_profile(profile: RiskQuestionnaireSubmission | None) -> dict:
    if not profile:
        return {"risk_level": "平衡型", "preference_tags": ["宽基", "中期配置"], "investment_horizon": "中期", "max_drawdown": "10%-15%", "summary": "默认画像为平衡型，建议先完成风险测评。"}
    return {"id": profile.id, "risk_level": profile.risk_level, "preference_tags": profile.preference_tags.split(","), "investment_horizon": profile.investment_horizon, "max_drawdown": profile.max_drawdown, "summary": profile.summary, "total_score": profile.total_score, "created_at": profile.created_at.isoformat(timespec="seconds")}


def serialize_report(report: AnalysisReport) -> dict:
    return {"id": report.id, "title": report.title, "etf_code": report.etf_code, "summary": report.summary, "recommendation": report.recommendation, "confidence": report.confidence, "created_at": report.created_at.isoformat(timespec="seconds")}


def handle_bootstrap(start_response):
    with session_scope() as session:
        user = session.get(User, "demo-user")
        profile = session.scalar(select(RiskQuestionnaireSubmission).where(RiskQuestionnaireSubmission.user_id == user.id).order_by(desc(RiskQuestionnaireSubmission.created_at)).limit(1))
        featured_codes = [item["code"] for item in ETF_CATALOG]
        target_featured_count = max(8, len(featured_codes))
        all_codes = list(session.scalars(select(ETFMaster.code)))
        unsupported_codes = effective_unsupported_etf_codes(all_codes)
        featured_map = {
            item.code: item
            for item in session.scalars(select(ETFMaster).where(ETFMaster.code.in_(featured_codes)))
        }
        featured = [featured_map[code] for code in featured_codes if code in featured_map and code not in unsupported_codes]
        if len(featured) < target_featured_count:
            fallback_stmt = select(ETFMaster).order_by(ETFMaster.code.asc())
            if unsupported_codes:
                fallback_stmt = fallback_stmt.where(~ETFMaster.code.in_(unsupported_codes))
            fallback = [
                item for item in session.scalars(fallback_stmt.limit(target_featured_count * 2))
                if item.code not in {featured_item.code for featured_item in featured}
            ]
            featured = (featured + fallback)[:target_featured_count]
        return json_response(start_response, {
            "user": {"id": user.id, "display_name": user.display_name},
            "risk_profile": serialize_risk_profile(profile),
            "data_sources": market_provider_status(),
            "news_sources": news_provider_status(),
            "model_providers": model_provider_status(),
            "featured_etfs": [{"code": item.code, "name": item.name, "category": item.category, "theme": item.theme, "risk_level": item.risk_level, "description": item.description} for item in featured],
        })


def handle_latest_risk(start_response, user_id: str):
    with session_scope() as session:
        profile = session.scalar(select(RiskQuestionnaireSubmission).where(RiskQuestionnaireSubmission.user_id == user_id).order_by(desc(RiskQuestionnaireSubmission.created_at)).limit(1))
        return json_response(start_response, serialize_risk_profile(profile))


def handle_create_risk(start_response, payload: dict):
    user_id = payload.get("user_id", "demo-user")
    answers = payload.get("answers", {})
    result = RiskEngine().evaluate(answers)
    with session_scope() as session:
        profile = RiskQuestionnaireSubmission(user_id=user_id, answers_json=str(answers), total_score=result.total_score, risk_level=result.risk_level, preference_tags=",".join(result.preference_tags), investment_horizon=result.investment_horizon, max_drawdown=result.max_drawdown, summary=result.summary)
        session.add(profile)
        session.flush()
        return json_response(start_response, serialize_risk_profile(profile))


def handle_list_etfs(start_response, query: str, category: str = ""):
    with session_scope() as session:
        stmt = select(ETFMaster).order_by(ETFMaster.code.asc())
        all_codes = list(session.scalars(select(ETFMaster.code)))
        unsupported_codes = effective_unsupported_etf_codes(all_codes)
        if unsupported_codes:
            stmt = stmt.where(~ETFMaster.code.in_(unsupported_codes))
        if query:
            like = f"%{query}%"
            stmt = stmt.where(or_(ETFMaster.code.like(like), ETFMaster.name.like(like), ETFMaster.theme.like(like)))
        if category:
            stmt = stmt.where(ETFMaster.category == category)
        etfs = list(session.scalars(stmt.limit(20)))
        return json_response(start_response, [{"code": etf.code, "name": etf.name, "category": etf.category, "theme": etf.theme, "benchmark": etf.benchmark, "risk_level": etf.risk_level, "description": etf.description} for etf in etfs])


def handle_etf_detail(start_response, etf_code: str):
    with session_scope() as session:
        unsupported_codes = effective_unsupported_etf_codes(list(session.scalars(select(ETFMaster.code))))
        if etf_code in unsupported_codes:
            return json_response(start_response, {"error": "该 ETF 暂无法获取行情数据，已从候选列表中隐藏。"}, status="404 Not Found")
        etf = session.get(ETFMaster, etf_code)
        if not etf:
            return json_response(start_response, {"error": "ETF not found"}, status="404 Not Found")
        quotes = list(session.scalars(select(ETFQuote).where(ETFQuote.etf_code == etf_code).order_by(ETFQuote.trade_date.asc())))
        if not quotes:
            try:
                SyncService(session).refresh_etf_quotes(etf_code, preferred_provider="auto", days=120)
                session.flush()
                quotes = list(session.scalars(select(ETFQuote).where(ETFQuote.etf_code == etf_code).order_by(ETFQuote.trade_date.asc())))
                if quotes:
                    unmark_etf_unsupported(etf_code)
            except Exception:
                mark_etf_unsupported(etf_code)
                return json_response(start_response, {"error": "该 ETF 暂无法获取行情数据，已从候选列表中隐藏。"}, status="404 Not Found")
        news = list(session.scalars(select(ETFNews).where(ETFNews.etf_code == etf_code).order_by(desc(ETFNews.published_at)).limit(8)))
        constituents = list(
            session.scalars(
                select(ETFConstituent)
                .where(ETFConstituent.etf_code == etf_code)
                .order_by(ETFConstituent.weight.desc())
                .limit(10)
            )
        )
        factor = session.scalar(select(ETFFactor).where(ETFFactor.etf_code == etf_code).order_by(desc(ETFFactor.as_of)).limit(1))
        return json_response(start_response, {
            "code": etf.code,
            "name": etf.name,
            "category": etf.category,
            "theme": etf.theme,
            "benchmark": etf.benchmark,
            "risk_level": etf.risk_level,
            "description": etf.description,
            "quotes": [{"trade_date": q.trade_date.isoformat(), "close_price": q.close_price, "pct_change": q.pct_change, "turnover": q.turnover} for q in quotes[-60:]],
            "news": [{"title": n.title, "source": n.source, "published_at": n.published_at.isoformat(timespec="seconds"), "sentiment": n.sentiment, "summary": n.summary} for n in news],
            "constituents": [{
                "stock_code": item.stock_code,
                "stock_name": item.stock_name,
                "weight": item.weight,
                "pe": item.pe,
                "pb": item.pb,
                "roe": item.roe,
                "revenue_growth": item.revenue_growth,
                "profit_growth": item.profit_growth,
                "sector": item.sector,
            } for item in constituents],
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
        })


def handle_refresh_etf(start_response, etf_code: str, payload: dict):
    preferred_provider = payload.get("provider", "auto")
    days = int(payload.get("days", 120))
    with session_scope() as session:
        result = SyncService(session).refresh_etf_dataset(etf_code, preferred_provider=preferred_provider, days=days)
        result["data_sources"] = market_provider_status()
        return json_response(start_response, result)


def handle_refresh_quotes(start_response, etf_code: str, payload: dict):
    preferred_provider = payload.get("provider", "auto")
    days = int(payload.get("days", 120))
    with session_scope() as session:
        result = SyncService(session).refresh_etf_quotes(etf_code, preferred_provider=preferred_provider, days=days)
        result["data_sources"] = market_provider_status()
        return json_response(start_response, result)


def handle_refresh_fundamentals(start_response, etf_code: str, payload: dict):
    max_items = int(payload.get("max_items", 10))
    with session_scope() as session:
        result = SyncService(session).refresh_etf_fundamentals(etf_code, max_items=max_items)
        return json_response(start_response, result)


def handle_refresh_factors(start_response, etf_code: str, payload: dict):
    with session_scope() as session:
        result = SyncService(session).refresh_etf_factors(etf_code)
        return json_response(start_response, result)


def handle_refresh_news(start_response, etf_code: str, payload: dict):
    preferred_provider = payload.get("provider", "auto")
    summarize_with = payload.get("summarize_with", "auto")
    limit = int(payload.get("limit", 6))
    with session_scope() as session:
        result = NewsSyncService(session).refresh_news(etf_code, preferred_provider=preferred_provider, limit=limit, summarize_with=summarize_with)
        result["news_sources"] = news_provider_status()
        result["model_providers"] = model_provider_status()
        return json_response(start_response, result)


def handle_create_analysis(start_response, payload: dict):
    user_id = payload.get("user_id", "demo-user")
    etf_code = payload["etf_code"]
    mode = payload.get("mode", "llm")
    with session_scope() as session:
        analysis = AnalysisService(session).build_analysis(etf_code, user_id, mode=mode)
        report = ReportService(session).create_report(user_id, analysis)
        return json_response(start_response, {"analysis": analysis, "report": serialize_report(report)})


def handle_list_reports(start_response, user_id: str):
    with session_scope() as session:
        reports = list(session.scalars(select(AnalysisReport).where(AnalysisReport.user_id == user_id).order_by(desc(AnalysisReport.created_at)).limit(20)))
        return json_response(start_response, [serialize_report(item) for item in reports])


def handle_report_detail(start_response, report_id: int):
    with session_scope() as session:
        report = session.get(AnalysisReport, report_id)
        if not report:
            return json_response(start_response, {"error": "Report not found"}, status="404 Not Found")
        return json_response(start_response, {**serialize_report(report), "report_html": report.report_html})


def handle_download_report(start_response, report_id: int):
    with session_scope() as session:
        report = session.get(AnalysisReport, report_id)
        if not report:
            return json_response(start_response, {"error": "Report not found"}, status="404 Not Found")
        return html_response(start_response, report.report_html, disposition=f"attachment; filename=report_{report_id}_{report.etf_code}.html")


def handle_delete_report(start_response, report_id: int):
    with session_scope() as session:
        report = session.get(AnalysisReport, report_id)
        if not report:
            return json_response(start_response, {"error": "Report not found"}, status="404 Not Found")
        report_path = REPORT_DIR / f"report_{report.id}_{report.etf_code}.html"
        if report_path.exists():
            report_path.unlink()
        session.delete(report)
        return json_response(start_response, {"ok": True, "id": report_id})


def handle_create_session(start_response, payload: dict):
    user_id = payload.get("user_id", "demo-user")
    etf_code = payload.get("etf_code")
    with session_scope() as session:
        chat_session = ChatService(session).create_session(user_id, etf_code)
        return json_response(start_response, {"id": chat_session.id, "user_id": chat_session.user_id, "etf_code": chat_session.etf_code, "title": chat_session.title, "created_at": chat_session.created_at.isoformat(timespec="seconds")})


def handle_get_session(start_response, session_id: int):
    with session_scope() as session:
        chat_session = session.get(ChatSession, session_id)
        if not chat_session:
            return json_response(start_response, {"error": "Chat session not found"}, status="404 Not Found")
        messages = list(session.scalars(select(ChatMessage).where(ChatMessage.session_id == session_id).order_by(ChatMessage.created_at.asc())))
        return json_response(start_response, {"id": chat_session.id, "etf_code": chat_session.etf_code, "title": chat_session.title, "messages": [{"id": msg.id, "role": msg.role, "expert_name": msg.expert_name, "content": msg.content, "created_at": msg.created_at.isoformat(timespec="seconds")} for msg in messages]})


def handle_send_message(start_response, session_id: int, payload: dict):
    content = payload.get("content", "").strip()
    if not content:
        return json_response(start_response, {"error": "content is required"}, status="400 Bad Request")
    with session_scope() as session:
        assistant = ChatService(session).reply(session_id, content)
        return json_response(
            start_response,
            {
                "id": assistant.id,
                "role": assistant.role,
                "expert_name": assistant.expert_name,
                "content": assistant.content,
                "thinking_steps": getattr(assistant, "thinking_steps", []),
                "created_at": assistant.created_at.isoformat(timespec="seconds"),
            },
        )

