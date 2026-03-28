# Reminder Agent MVP

一个基于 FastAPI 的提醒型 Agent MVP，包含后端接口、调度器、SQLite 数据库和内置聊天页面。

## 本地启动

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
uvicorn app.main:app --reload
```

启动后可访问：

- `http://127.0.0.1:8000/docs`
- `http://127.0.0.1:8000/chat`

## Gemini 配置

在 `.env` 中填写：

```bash
GEMINI_API_KEY=your_api_key
GEMINI_MODEL=gemini-2.5-flash
```

如果没有配置 `GEMINI_API_KEY`，`/api/agent/chat` 仍然可访问，但会返回配置提示，而不会调用模型。

## 魔搭备用模型

当前项目支持在 Gemini 配额耗尽时自动切换到魔搭社区 API-Inference。

在 `.env` 中填写：

```bash
MODELSCOPE_API_KEY=your_modelscope_token
MODELSCOPE_MODEL=Qwen/Qwen2.5-72B-Instruct
MODELSCOPE_BASE_URL=https://api-inference.modelscope.cn/v1
```

根据魔搭社区的 API-Inference 官方说明，可以使用 OpenAI 风格的 `chat.completions` 接口，`base_url` 为 `https://api-inference.modelscope.cn/v1`，模型名使用对应的 Model ID。

## Telegram 配置

如果你要测试 Telegram 通知或 Webhook，请继续填写：

```bash
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TELEGRAM_API_BASE=https://api.telegram.org
```

## 网页通知

当前项目已经支持 `web` 通知通道：

- 到期后会写入网页通知收件箱
- 打开 `/chat` 页面时会自动轮询新提醒
- 可以直接在页面里点 `完成` 或 `延后 10 分钟`

如果你想优先走本地 MVP，建议创建提醒时把 `channel_type` 设成 `web`。

## 邮件提醒

当前项目也支持 SMTP 邮件发送。你需要在 `.env` 中继续填写：

```bash
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USERNAME=your_account
SMTP_PASSWORD=your_password
SMTP_FROM_EMAIL=your_email@example.com
SMTP_USE_TLS=true
```

然后在注册用户时保存 `email`，创建提醒时把 `channel_type` 设成 `email`。

## 云部署

推荐先用 Railway，原因是：

- 会自动给你一个公网可访问的 URL
- 默认自带 HTTPS，适合 Telegram Webhook
- 支持挂载 Volume，适合当前这个 SQLite MVP

### 1. 把代码推到 GitHub

云平台通常直接从 GitHub 拉代码构建，所以先把当前项目推到一个仓库。

### 2. 在 Railway 新建项目

- 选择 `Deploy from GitHub repo`
- 选中你的仓库
- Railway 会检测到本项目里的 [Dockerfile](/E:/共享/chat/reminder/Dockerfile) 并自动构建

### 3. 配置环境变量

在 Railway 的服务环境变量里填写：

```bash
APP_ENV=prod
DEFAULT_TIMEZONE=Asia/Shanghai
GEMINI_API_KEY=你的Gemini密钥
GEMINI_MODEL=gemini-2.5-flash
TELEGRAM_BOT_TOKEN=你的Telegram机器人token
TELEGRAM_API_BASE=https://api.telegram.org
DATABASE_URL=sqlite:////app/data/reminder.db
```

说明：

- `DATABASE_URL` 必须指向挂载卷里的绝对路径，否则 SQLite 数据在重启或重新部署后可能丢失
- 当前项目已经支持自动创建 SQLite 数据目录

### 4. 挂载 Volume

在 Railway 给这个服务挂一个 Volume，挂载路径设为：

```text
/app/data
```

这样 `sqlite:////app/data/reminder.db` 就会真正持久化。

### 5. 部署成功后访问

部署完成后，Railway 会给你一个公网域名。你可以直接打开：

- `https://你的域名/docs`
- `https://你的域名/chat`

### 6. 配置 Telegram Webhook

部署成功后，把下面这个地址放进浏览器：

```text
https://api.telegram.org/bot你的TOKEN/setWebhook?url=https://你的域名/api/bot/telegram/webhook
```

成功后，Telegram 发给你机器人的消息就会进入这个项目。

## 快速体验

1. 先创建用户：

```bash
curl -X POST http://127.0.0.1:8000/api/users/register ^
  -H "Content-Type: application/json" ^
  -d "{\"username\":\"demo\",\"display_name\":\"Demo User\",\"timezone\":\"Asia/Shanghai\"}"
```

2. 打开 `http://127.0.0.1:8000/chat`
3. 把返回的 `user_id` 填进页面
4. 直接发送自然语言，比如“明天下午三点提醒我交论文初稿”

## 最小闭环接口

- `POST /api/agent/chat`
- `POST /api/reminders`
- `GET /api/reminders`
- `GET /api/reminders/{id}`
- `PATCH /api/reminders/{id}`
- `DELETE /api/reminders/{id}`
- `POST /api/reminders/{id}/snooze`
- `POST /api/reminders/{id}/done`
- `POST /api/scheduler/scan-due-reminders`
- `GET /api/notifications/logs`
