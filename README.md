# Reminder Agent MVP + AI Daily Scout

这个仓库当前同时包含两个可独立运行的子系统：

- `Reminder Agent MVP`：一个基于 FastAPI 的提醒服务，提供 API、调度、通知和简单 Web 页面
- `AI Daily Scout`：一个面向个人使用的每日 AI 资讯简报工具，抓取 RSS 后生成中文 Markdown 日报

## AI Daily Scout

一个面向个人使用的每日 AI 资讯简报工具。

它会自动从配置好的资讯源抓取当天新的 AI 新闻、产品、应用和开源动态，经过基础过滤、去重、分类与摘要后，输出一份中文 Markdown 日报。第一版以本地运行和本地存储为主，后续可以扩展为邮件、Telegram 或飞书推送。

---

## 功能特性

- 支持从多个 RSS 源抓取资讯
- 支持基础关键词过滤
- 支持 SQLite 本地存储
- 支持 URL / hash 去重
- 支持调用 OpenAI Responses API 生成中文摘要
- 支持输出 Markdown 日报
- 项目结构清晰，便于后续扩展

---

## 项目结构

```text
reminder/
├─ app/
│  ├─ api/
│  ├─ core/
│  ├─ models/
│  ├─ repositories/
│  ├─ services/
│  ├─ static/
│  ├─ utils/
│  ├─ scout/
│  │  ├─ config/
│  │  ├─ delivery/
│  │  ├─ fetchers/
│  │  ├─ pipeline/
│  │  ├─ storage/
│  │  ├─ utils/
│  │  └─ main.py
│  └─ main.py
├─ data/
├─ reports/
├─ tests/
├─ .env
├─ requirements.txt
├─ run_daily.py
└─ README.md
```

---

## 环境要求

- Python 3.11+
- SQLite
- OpenAI API Key

---

## 安装步骤

### 1. 创建虚拟环境并激活

Windows:

```bash
python -m venv .venv
.venv\Scripts\activate
```

macOS / Linux:

```bash
python -m venv .venv
source .venv/bin/activate
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 配置环境变量

复制 `.env.example` 为 `.env`，并填写你的配置：

```env
OPENAI_API_KEY=your_openai_api_key_here
OPENAI_MODEL=gpt-5.4
SCOUT_DATABASE_PATH=data/scout.db
SCOUT_SOURCES_FILE=app/scout/config/sources.yaml
REPORT_TIMEZONE=Asia/Shanghai
REPORT_LANGUAGE=zh-CN
REPORT_TOP_N=20
SCOUT_RECENT_DAYS=3
SCOUT_MAX_SUMMARY_ITEMS=30
SCOUT_LOG_LEVEL=INFO
```

### 4. 配置资讯源

编辑：

```text
app/scout/config/sources.yaml
```

确保至少有 1 个 `enabled: true` 的 RSS 源。

---

## 运行方式

### Reminder Agent MVP

```bash
uvicorn app.main:app --reload
```

### AI Daily Scout

方式一：直接运行主流程

```bash
python -m app.scout.main
```

方式二：运行统一入口

```bash
python run_daily.py
```

### GitHub Actions 定时运行

仓库已包含工作流：

```text
.github/workflows/ai-daily-scout.yml
```

使用前请在 GitHub 仓库里配置：

- `OPENAI_API_KEY`：Actions Secret
- 可选 Actions Variables：`OPENAI_MODEL`、`REPORT_TIMEZONE`、`REPORT_LANGUAGE`、`REPORT_TOP_N`、`SCOUT_RECENT_DAYS`、`SCOUT_MAX_SUMMARY_ITEMS`

工作流支持手动触发和每日定时运行，执行后会上传：

- `reports/` 日报文件
- `data/scout.db` 数据库文件

---

## 输出结果

AI Daily Scout 运行后会生成：

- SQLite 数据库：`data/scout.db`
- 当日日报：`reports/YYYY-MM-DD.md`

如果当天没有新增文章，程序会尝试从数据库中取最近时间窗内的已存文章，重新生成当天日报。

---

## 当前处理流程

1. 读取 `sources.yaml`
2. 抓取启用的 RSS 源
3. 标准化字段
4. 先按发布时间过滤最近内容
5. 写入 SQLite
6. 去重
7. 仅对前 N 条重点内容调用模型生成摘要
8. 输出 Markdown 日报

---

## 后续规划

- 邮件推送
- Telegram 推送
- 更强的标题相似去重
- 重要性评分
- 历史日报检索
- 个性化偏好过滤

---

## 常见问题

### 1. 没有生成日报怎么办？

请先检查：

- `.env` 是否配置正确
- `OPENAI_API_KEY` 是否有效
- RSS 源是否可访问
- `reports/` 目录是否可写

### 2. 模型摘要失败怎么办？

程序会回退到原始摘要，并继续生成日报。请检查：

- 网络连接
- API Key
- 请求配额
- 日志输出

### 3. 数据重复很多怎么办？

第一版主要基于 URL 和 hash 去重，后续可以增加标题相似度去重。

---

## Reminder Agent MVP

当前提醒系统仍然保留，适合继续本地联调或部署到 Railway。

本地启动：

```bash
uvicorn app.main:app --reload
```

启动后可访问：

- `http://127.0.0.1:8000/docs`
- `http://127.0.0.1:8000/chat`

---

## License

仅供个人学习与原型开发使用。
