# Railway 部署说明

这个项目已经有 `Dockerfile`，最省力的云部署方式是直接用 Railway 从 GitHub 拉代码构建。

仓库里还额外放了两个文件，方便你直接部署：

- `railway.toml`：固定 Dockerfile 构建、健康检查和重启策略
- `.env.railway.example`：可直接复制到 Railway 变量面板的模板

## 适用前提

- 当前项目使用 SQLite
- 应用内有 APScheduler 定时扫描提醒
- 因为用了 SQLite 和进程内调度器，云上建议只跑 1 个实例

如果后面要扩成多实例，再考虑把数据库换成 Postgres，并把调度任务拆出来。

## 1. 推送代码到 GitHub

先把项目推到一个 GitHub 仓库。

建议不要提交这些本地内容：

- `.env`
- `reminder.db`
- `*.pem`

## 2. 在 Railway 创建项目

1. 打开 Railway
2. 选择 `Deploy from GitHub repo`
3. 选择这个仓库
4. Railway 会检测到仓库里的 `Dockerfile` 并自动构建

## 3. 配置环境变量

在 Railway 的服务环境变量里填写：

```env
APP_ENV=prod
DEFAULT_TIMEZONE=Asia/Shanghai
DATABASE_URL=sqlite:////app/data/reminder.db
SCHEDULER_SCAN_INTERVAL_SECONDS=60
```

也可以直接参考仓库里的 `.env.railway.example` 逐项粘贴。

如果你要启用大模型，再补：

```env
GEMINI_API_KEY=你的密钥
GEMINI_MODEL=gemini-2.5-flash
```

如果 Gemini 不可用，项目也支持备用配置：

```env
MODELSCOPE_API_KEY=你的密钥
MODELSCOPE_MODEL=Qwen/Qwen2.5-72B-Instruct
MODELSCOPE_BASE_URL=https://api-inference.modelscope.cn/v1
```

如果你还要启用 Telegram：

```env
TELEGRAM_BOT_TOKEN=你的机器人Token
TELEGRAM_API_BASE=https://api.telegram.org
```

如果你要启用企业微信群机器人：

```env
WECOM_BOT_WEBHOOK=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=你的key
WECOM_BOT_MENTIONED_MOBILE_LIST=
```

`WECOM_BOT_MENTIONED_MOBILE_LIST` 可以留空；如果你想在群里额外 @ 某些手机号，就填英文逗号分隔的手机号列表。

如果要启用邮件提醒：

```env
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USERNAME=your_account
SMTP_PASSWORD=your_password
SMTP_FROM_EMAIL=your_email@example.com
SMTP_USE_TLS=true
```

## 4. 挂载持久化 Volume

SQLite 必须挂持久化卷，否则重建服务后数据会丢。

给 Railway 服务挂一个 Volume，挂载路径设为：

```text
/app/data
```

然后 `DATABASE_URL` 保持为：

```text
sqlite:////app/data/reminder.db
```

## 5. 部署后验证

部署成功后，访问：

- `/`
- `/docs`
- `/chat`

例如：

```text
https://你的域名/
https://你的域名/docs
https://你的域名/chat
```

根路径返回类似下面的 JSON，说明服务已经启动：

```json
{"success": true, "message": "Reminder Agent MVP is running"}
```

## 6. Telegram Webhook

如果你启用了 Telegram，可以在浏览器中打开：

```text
https://api.telegram.org/bot你的TOKEN/setWebhook?url=https://你的域名/api/bot/telegram/webhook
```

## 7. 当前架构的云上注意事项

- 只部署 1 个副本，避免定时任务重复执行
- SQLite 适合 MVP，不适合高并发
- 重建容器前确认 Volume 仍然挂载在 `/app/data`
- 不要把本地 `.env` 和私钥文件提交到仓库

## 8. 首次上线建议

推荐先完成这套最小闭环：

1. 只开 `web` 通知或 `chat` 页面
2. 先确认创建提醒和定时扫描正常
3. 再接入 Gemini 或 Telegram
4. 稳定后再考虑邮件提醒和数据库升级
