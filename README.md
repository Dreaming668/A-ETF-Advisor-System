# A股 ETF 智能投顾系统

一个围绕 A 股 ETF 场景构建的端到端智能投顾原型系统，覆盖风险测评、ETF 检索、行情/新闻/基本面/因子同步、五专家分析、报告生成与多轮问答。

当前版本已经从“演示型规则拼装”升级到“真实数据 + LLM 直生分析”的实现路径，适合课程项目展示、原型验证、功能演示和后续工程化扩展。

---

## 1. 项目定位

本项目的目标不是做一个通用资讯站，而是构建一个**围绕单只 ETF 决策闭环**的投顾系统：

- 用户先完成风险测评，得到风险等级与偏好标签
- 系统支持在全量 A 股 ETF 范围内搜索、筛选和浏览
- 数据层分别同步行情、新闻、成分股基本面、Alpha 因子
- 分析层由五位专家协同生成结论
- 用户可以继续围绕同一只 ETF 进行多轮问答
- 最终结果可归档为 HTML 报告并下载

---

## 2. 当前能力总览

### 2.1 用户侧功能

- 风险问卷与风险画像生成
- ETF 搜索、分类筛选、滚动浏览
- 重点 ETF 展示
- ETF 详情预览与近 40 日走势展示
- 四类独立刷新动作
  - 刷新行情
  - 刷新新闻
  - 刷新基本面
  - 刷新因子
- 五专家分析报告生成
- 历史报告查看、下载、删除
- 基于当前 ETF 上下文的多轮投顾问答

### 2.2 系统侧能力

- SQLite 本地持久化
- 启动时自动建库与基础数据引导
- 数据源状态探测
- 无法稳定获取完整数据的 ETF 自动隐藏
- 报告导出到 `data/reports/`
- 前后端一体化部署，浏览器直接访问即可使用

---

## 3. 五专家模型

系统当前采用“五专家 + 通用专家整合”的分析结构：

- 市场专家：基于 ETF 行情、涨跌幅、波动率、成交额比等量价指标判断趋势与交易拥挤度
- 新闻分析师：基于中文财经门户抓取结果，分析事件、情绪和催化链条
- Alpha 分析师：基于动量、波动、流动性、资金流、估值、行业轮动等因子输出风格判断
- 基本面分析师：基于 ETF 成分股、权重、PE/PB/ROE/成长性做组合层基本面分析
- 通用专家：结合前四位专家观点和用户风险画像，形成投资建议与风险提示

### 重要说明

- 当前分析默认使用 **LLM 直接生成**，不再启用规则型回退分析
- 如果未配置 `OPENAI_API_KEY`，报告生成与问答相关能力将不可用
- 基本面分析**不允许使用兜底假数据**
  - 有真实成分股数据就展示
  - 没有就明确提示“获取不到”

---

## 4. 数据链路

### 4.1 行情数据

- 主源：腾讯财经 ETF 历史 K 线
- 备选：新浪财经 K 线
- 用途：
  - ETF 行情刷新
  - 详情页顶部指标
  - 走势曲线
  - Alpha 因子计算输入

### 4.2 新闻数据

- 来源：中文财经站点聚合抓取
- 当前覆盖：
  - 东方财富网/基金频道相关页面
  - 新浪财经
  - 同花顺财经
  - 证券时报
  - 财联社
- 用途：
  - ETF 新闻刷新
  - 新闻分析师输入
  - 问答上下文补充

### 4.3 基本面数据

- ETF 持仓来源：东方财富 `FundArchivesDatas.aspx`
- 个股财务摘要：新浪 `CompanyFinanceService.getFinanceReport2022`
- 个股快照：东方财富 `push2.eastmoney.com`

### 4.4 Alpha 因子

当前因子引擎 `LiveFactorEngine` 计算：

- 动量
- 波动
- 流动性
- 资金流
- 估值
- 行业轮动
- 综合得分

### 4.5 已知限制

当前项目里最敏感的数据链路是**成分股基本面**：

- ETF 持仓页通常可以访问
- 新浪财务摘要通常可以访问
- 东方财富 `push2.eastmoney.com` 个股快照在某些网络/代理/TUN 环境下可能被直接断开连接

如果遇到“基本面刷新失败”或“因子刷新失败”，优先排查本机网络环境、代理软件、VPN、TUN 模式，而不是先怀疑数据库或前端逻辑。

---

## 5. 技术架构

### 5.1 后端

- Python
- WSGI：`wsgiref.simple_server`
- ORM：SQLAlchemy 2.x
- 数据库：SQLite
- HTTP：`requests`
- HTML 解析：BeautifulSoup

### 5.2 前端

- 原生 HTML / CSS / JavaScript
- 无额外前端框架
- 单页应用式交互，静态资源由后端直接托管

### 5.3 模型层

- OpenAI Responses API
- 当前默认模型来自环境变量 `OPENAI_MODEL`
- 默认示例值：`gpt-5-mini`

---

## 6. 目录结构

```text
ETF投顾系统/
├─ backend/
│  ├─ app/
│  │  ├─ services/         # 数据同步、分析、问答、模型、新闻、因子等核心服务
│  │  ├─ static/           # 前端 JS / CSS
│  │  ├─ templates/        # 页面模板
│  │  ├─ server.py         # 主 WSGI 路由入口
│  │  ├─ models.py         # 数据模型
│  │  ├─ database.py       # 数据库初始化与 session 管理
│  │  ├─ bootstrap.py      # 启动引导与基础数据
│  │  └─ catalog.py        # 重点 ETF 清单
│  └─ instance/
│     └─ advisor.db        # SQLite 数据库文件
├─ data/
│  ├─ reports/             # 生成的 HTML 报告
│  └─ unsupported_etf_codes.json
├─ docs/
│  └─ A股ETF智能投顾系统设计.md
├─ scripts/
│  ├─ init_db.py
│  ├─ sync_market_data.py
│  ├─ sync_fundamentals.py
│  ├─ sync_news.py
│  ├─ sync_all_data.py
│  └─ verify_openai.py
├─ run.py
├─ .env.example
├─ requirements.txt
└─ README.md
```

---

## 7. 数据库与存储

### 7.1 SQLite 路径

- 数据库文件：`backend/instance/advisor.db`

### 7.2 报告输出目录

- 报告目录：`data/reports/`
- 格式：HTML

### 7.3 其他运行数据

- 不可用 ETF 列表：`data/unsupported_etf_codes.json`

---

## 8. 启动方式

### 8.1 安装依赖

当前 `requirements.txt` 只包含最小依赖，建议安装时补齐运行所需库：

```bash
pip install -r requirements.txt
pip install requests beautifulsoup4
```

### 8.2 初始化数据库

```bash
python scripts/init_db.py
```

该步骤会：

- 初始化 SQLite 表结构
- 写入基础用户 `demo-user`
- 引导 ETF 主数据

### 8.3 启动服务

```bash
python run.py
```

默认地址：

```text
http://127.0.0.1:5000
```

---

## 9. 环境变量

项目会自动读取根目录 `.env` 文件。

### 9.1 OpenAI 相关

```env
OPENAI_API_KEY=你的密钥
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-5-mini
OPENAI_TIMEOUT=45
```

### 9.2 说明

- 若未设置 `OPENAI_API_KEY`
  - 首页、搜索、详情浏览、数据刷新仍可使用
  - 报告生成与多轮问答将不可用

---

## 10. 常用数据同步脚本

### 10.1 初始化全部默认数据

```bash
python scripts/sync_all_data.py
```

默认会对一组预设 ETF 执行：

- 行情刷新
- 基本面刷新
- 因子刷新
- 新闻刷新

### 10.2 只刷新行情

```bash
python scripts/sync_market_data.py
```

### 10.3 只刷新基本面与因子

```bash
python scripts/sync_fundamentals.py
```

### 10.4 只刷新新闻

```bash
python scripts/sync_news.py
```

### 10.5 验证 OpenAI 配置

```bash
python scripts/verify_openai.py
```

---

## 11. Web 端交互说明

### 11.1 重点 ETF

首页当前内置 8 只重点 ETF，用于首屏展示和快速进入分析：

- 510300 沪深300ETF
- 510050 上证50ETF
- 159915 创业板ETF
- 512100 中证1000ETF
- 515880 通信ETF
- 510500 中证500ETF
- 588000 科创50ETF
- 515180 红利ETF

### 11.2 ETF 搜索区

支持：

- 按代码、名称、主题搜索
- 按 ETF 类型筛选
- 表格纵向滚动浏览

### 11.3 四类刷新动作

当前已拆分为 4 个独立动作，避免一个动作失败拖垮全部链路：

- 刷新行情
  - 仅刷新 ETF 行情数据
  - 完成后顶部收盘价、涨跌幅等指标会立即更新
- 刷新新闻
  - 抓取 ETF 相关中文财经新闻并做摘要
- 刷新基本面
  - 刷新真实成分股与其财务快照
- 刷新因子
  - 仅基于当前已存在的行情 + 基本面计算因子
  - 若基本面为空，将直接报错，不使用假数据

### 11.4 生成报告

点击“生成报告”后会：

- 构造完整分析上下文
- 调用五位专家
- 生成综合结论
- 写入数据库
- 输出 HTML 报告

### 11.5 多轮问答

问答会自动带入：

- 当前 ETF 基础信息
- 最新行情摘要
- 最新因子结果
- 最新新闻摘要
- 前几大成分股
- 用户风险画像
- 最近报告摘要
- 最近会话历史

前端会展示简化版“思考过程”提示，但不会暴露真实模型内部推理。

---

## 12. 主要 API 路由

### 12.1 系统与初始化

- `GET /api/health`
- `GET /api/bootstrap`
- `GET /api/system/data-sources`
- `GET /api/system/news-sources`
- `GET /api/system/model-providers`

### 12.2 风险测评

- `GET /api/risk-assessments/latest`
- `POST /api/risk-assessments`

### 12.3 ETF

- `GET /api/etfs`
- `GET /api/etfs/{code}`
- `POST /api/etfs/{code}/quotes/refresh`
- `POST /api/etfs/{code}/news/refresh`
- `POST /api/etfs/{code}/fundamentals/refresh`
- `POST /api/etfs/{code}/factors/refresh`

### 12.4 分析与报告

- `POST /api/analysis/reports`
- `GET /api/reports`
- `GET /api/reports/{id}`
- `GET /api/reports/{id}/download`
- `DELETE /api/reports/{id}`

### 12.5 多轮问答

- `POST /api/chat/sessions`
- `GET /api/chat/sessions/{id}`
- `POST /api/chat/sessions/{id}/messages`

---

## 13. 关键实现约束

### 13.1 基本面真实性约束

- 基本面分析师不能使用兜底假数据
- 成分股没有真实数据时，界面直接提示“获取不到真实成分股信息”
- 因子计算也不允许在缺失真实成分股时伪造结果

### 13.2 ETF 可用性筛除机制

项目会对无法稳定获取数据的 ETF 进行隐藏处理，防止用户在前台频繁点到不可用标的。

相关逻辑位于：

- `backend/app/services/etf_availability_service.py`

### 13.3 数据刷新语义约束

当前前端按钮语义已经和后端行为对齐：

- “刷新行情”只刷新行情
- “刷新新闻”只刷新新闻
- “刷新基本面”只刷新成分股基本面
- “刷新因子”只刷新因子

不再出现“点刷新行情却连带刷新基本面和因子”的混淆行为。

---

## 14. 已知问题与排障建议

### 14.1 基本面刷新失败

常见原因：

- 东方财富 `push2` 个股快照接口被当前网络环境拦截
- 本机代理、TUN、VPN、透明隧道改写了解析或出口
- 成分股实时快照请求被远端主动断开

优先排查：

- 本机代理软件
- TUN / 全局模式
- VPN
- `push2.eastmoney.com` 是否被重写解析

### 14.2 ETF 列表突然明显变少

优先检查：

- `data/unsupported_etf_codes.json`
- `effective_unsupported_etf_codes()` 的筛除结果

### 14.3 报告生成失败

优先检查：

- `.env` 中是否配置 `OPENAI_API_KEY`
- `python scripts/verify_openai.py` 是否返回成功
- 外网是否可访问 `OPENAI_BASE_URL`

### 14.4 前端能打开，但问答/报告不可用

通常是：

- 模型层不可用
- 不是 Web 服务本身故障

---

## 15. 适合继续扩展的方向

- 将 `requirements.txt` 补齐为完整依赖清单
- 将 WSGI 开发服务器替换为 Gunicorn / Uvicorn 等正式运行方案
- 引入 PostgreSQL / TimescaleDB 替代 SQLite
- 增加认证、用户体系、自选 ETF、预警订阅
- 增加定时任务/批处理调度
- 引入更稳定的专业财经资讯源
- 为新闻摘要、专家结论和问答上下文加入缓存与异步化
- 增加更严格的可观测性与日志追踪

---

## 16. 适合作为答辩或交接时的简述

一句话概括：

> 这是一个以 A 股 ETF 为对象、以真实数据同步为基础、以五专家协同分析和多轮问答为核心交互的智能投顾原型系统。

如果你后面还想继续把 README 往“课程报告版”或“开源项目版”再分化，我也可以继续帮你拆成：

- `README.md`：面向使用者
- `docs/ARCHITECTURE.md`：面向开发者
- `docs/OPERATIONS.md`：面向部署和排障
