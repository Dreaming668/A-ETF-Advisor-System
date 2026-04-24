from __future__ import annotations

from pathlib import Path

from ..config import REPORT_DIR
from ..models import AnalysisReport


class ReportService:
    def __init__(self, session):
        self.session = session

    def create_report(self, user_id: str, analysis: dict) -> AnalysisReport:
        etf = analysis["etf"]
        general = analysis["experts"]["general"]
        html = self._build_report_html(analysis)

        report = AnalysisReport(
            user_id=user_id,
            etf_code=etf["code"],
            title=f"{etf['name']}智能投顾分析报告",
            summary=general["summary"],
            recommendation=general["recommendation"],
            confidence=general["confidence"],
            report_html=html,
        )
        self.session.add(report)
        self.session.flush()

        report_file = Path(REPORT_DIR) / f"report_{report.id}_{etf['code']}.html"
        report_file.write_text(html, encoding="utf-8")
        return report

    def _build_report_html(self, analysis: dict) -> str:
        etf = analysis["etf"]
        latest = analysis["latest_quote"]
        experts = analysis["experts"]
        profile = analysis["risk_profile"]

        def section(title: str, data: dict) -> str:
            signal_items = "".join(f"<li>{item}</li>" for item in data.get("signals", []))
            risk_items = "".join(f"<li>{item}</li>" for item in data.get("risks", []))
            return f"""
            <section class=\"card\">
              <h2>{title}</h2>
              <p>{data.get('summary', '')}</p>
              <h3>关键信号</h3>
              <ul>{signal_items}</ul>
              <h3>风险提示</h3>
              <ul>{risk_items}</ul>
            </section>
            """

        sections = "".join(
            [
                section("市场专家", experts["market"]),
                section("新闻分析师", experts["news"]),
                section("Alpha分析师", experts["alpha"]),
                section("基本面分析师", experts["fundamental"]),
                section("通用专家", experts["general"]),
            ]
        )

        return f"""
        <!DOCTYPE html>
        <html lang=\"zh-CN\">
        <head>
          <meta charset=\"UTF-8\" />
          <title>{etf['name']}智能投顾分析报告</title>
          <style>
            body {{ font-family: \"Microsoft YaHei\", sans-serif; background: #f3f0e8; color: #1e2430; margin: 0; padding: 24px; }}
            .wrap {{ max-width: 960px; margin: 0 auto; }}
            .hero {{ background: linear-gradient(135deg, #ffd7a8, #f5a65b); color: #1f2127; border-radius: 24px; padding: 24px; }}
            .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 16px; margin-top: 18px; }}
            .card {{ background: #fffdf7; border-radius: 18px; padding: 18px; box-shadow: 0 10px 30px rgba(31, 33, 39, 0.08); }}
            h1, h2, h3 {{ margin-top: 0; }}
            ul {{ padding-left: 18px; }}
          </style>
        </head>
        <body>
          <div class=\"wrap\">
            <section class=\"hero\">
              <h1>{etf['name']} ({etf['code']}) 智能投顾分析报告</h1>
              <p>{etf['description']}</p>
              <p>最新日期：{latest['trade_date']} | 收盘价：{latest['close_price']} | 20日涨跌幅：{latest['change_20d']}%</p>
              <p>综合建议：<strong>{experts['general']['recommendation']}</strong> | 置信度：{experts['general']['confidence']}</p>
              <p>用户画像：{profile['risk_level']} / {profile['investment_horizon']} / 最大回撤 {profile['max_drawdown']}</p>
            </section>
            <div class=\"grid\">{sections}</div>
          </div>
        </body>
        </html>
        """
