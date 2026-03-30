import json
import re
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from google.genai import errors, types
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.repositories.conversation_repository import ConversationRepository
from app.repositories.user_repository import UserRepository
from app.schemas.agent import AgentChatRequest
from app.schemas.reminder import ReminderCreateRequest, ReminderUpdateRequest
from app.services.gemini_service import GeminiService
from app.services.modelscope_service import ModelScopeService
from app.services.reminder_service import ReminderService


class AgentService:
    pending_plan_store: dict[str, dict[str, Any]] = {}
    pending_delete_store: dict[str, dict[str, Any]] = {}
    pending_change_store: dict[str, dict[str, Any]] = {}
    conversation_target_store: dict[str, dict[str, Any]] = {}

    def __init__(self, db: Session):
        self.db = db
        self.settings = get_settings()
        self.user_repo = UserRepository(db)
        self.reminder_service = ReminderService(db)
        self.conversation_repo = ConversationRepository(db)
        self.gemini_service = GeminiService()
        self.modelscope_service = ModelScopeService()

    async def chat(self, payload: AgentChatRequest) -> dict[str, Any]:
        user = self.user_repo.get_by_id(payload.user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        local_result = self._try_local_action(payload, user.id)
        if local_result is not None:
            self._log(payload, local_result["intent"], local_result["intent"], local_result.get("tool_payload"), local_result["reply"])
            return {
                "intent": local_result["intent"],
                "reply": local_result["reply"],
                "tool_result": local_result.get("tool_result"),
            }

        plan_result = await self._try_model_plan_create(payload, user.timezone, user.id)
        if plan_result is not None:
            self._log(
                payload,
                plan_result["intent"],
                plan_result["intent"],
                plan_result.get("tool_payload"),
                plan_result["reply"],
            )
            return {
                "intent": plan_result["intent"],
                "reply": plan_result["reply"],
                "tool_result": plan_result.get("tool_result"),
            }

        json_create_result = await self._try_model_json_create(payload, user.timezone, user.id)
        if json_create_result is not None:
            self._log(
                payload,
                json_create_result["intent"],
                json_create_result["intent"],
                json_create_result.get("tool_payload"),
                json_create_result["reply"],
            )
            return {
                "intent": json_create_result["intent"],
                "reply": json_create_result["reply"],
                "tool_result": json_create_result.get("tool_result"),
            }

        if self.gemini_service.is_configured:
            try:
                return await self._run_gemini_chat(payload, user.timezone, user.id)
            except errors.ClientError as exc:
                if self._should_fallback_to_modelscope(exc) and self.modelscope_service.is_configured:
                    try:
                        return await self._run_modelscope_chat(payload, user.timezone, user.id)
                    except Exception:
                        reply = "Gemini 额度已用完，魔搭备用模型也暂时不可用。你可以稍后再试，或者先去 /docs 手动创建提醒。"
                        self._log(payload, "provider_error", None, None, reply)
                        return {"intent": "provider_error", "reply": reply, "tool_result": None}
                reply = self._handle_gemini_client_error(exc)
                self._log(payload, "provider_error", None, None, reply)
                return {"intent": "provider_error", "reply": reply, "tool_result": None}
            except Exception:
                pass

        if self.modelscope_service.is_configured:
            try:
                return await self._run_modelscope_chat(payload, user.timezone, user.id)
            except Exception:
                reply = "当前智能解析暂时不可用。你可以稍后再试，或者先去 /docs 手动创建提醒。"
                self._log(payload, "provider_error", None, None, reply)
                return {"intent": "provider_error", "reply": reply, "tool_result": None}

        reply = "还没有配置可用的大模型密钥。请先在 .env 里填写 GEMINI_API_KEY 或 MODELSCOPE_API_KEY。"
        self._log(payload, "configuration_error", None, None, reply)
        return {"intent": "configuration_error", "reply": reply, "tool_result": None}

    async def _run_gemini_chat(self, payload: AgentChatRequest, timezone: str, user_id: int) -> dict[str, Any]:
        history = [types.Content(role="user", parts=[types.Part(text=payload.message)])]
        config = types.GenerateContentConfig(
            system_instruction=self._build_system_prompt(timezone),
            tools=[types.Tool(function_declarations=self._tool_schemas_gemini())],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        current_response = await self.gemini_service.client.aio.models.generate_content(
            model=self.settings.gemini_model,
            contents=history,
            config=config,
        )

        last_tool_name = None
        last_tool_payload = None
        last_tool_result = None

        for _ in range(5):
            function_calls = list(getattr(current_response, "function_calls", []) or [])
            if not function_calls:
                break

            if current_response.candidates:
                history.append(current_response.candidates[0].content)

            tool_outputs = []
            for call in function_calls:
                arguments = self._normalize_args(getattr(call, "args", {}) or {})
                tool_name = getattr(call, "name", "")
                result = self._execute_tool(tool_name, arguments, user_id, payload.channel)
                tool_outputs.append(types.Part.from_function_response(name=tool_name, response={"result": result}))
                last_tool_name = tool_name
                last_tool_payload = arguments
                last_tool_result = result

            history.append(types.Content(role="tool", parts=tool_outputs))
            current_response = await self.gemini_service.client.aio.models.generate_content(
                model=self.settings.gemini_model,
                contents=history,
                config=config,
            )

        reply = self._finalize_reply(getattr(current_response, "text", ""), last_tool_name, last_tool_result)
        intent = self._map_intent(last_tool_name)
        self._log(payload, intent, last_tool_name, last_tool_payload, reply)
        return {"intent": intent, "reply": reply, "tool_result": last_tool_result}

    async def _run_modelscope_chat(self, payload: AgentChatRequest, timezone: str, user_id: int) -> dict[str, Any]:
        messages = [
            {"role": "system", "content": self._build_system_prompt(timezone)},
            {"role": "user", "content": payload.message},
        ]

        last_tool_name = None
        last_tool_payload = None
        last_tool_result = None

        for _ in range(5):
            response = await self.modelscope_service.create_chat_completion(
                messages=messages,
                tools=self._tool_schemas_openai(),
                tool_choice=self._choose_modelscope_tool(messages[-1]["content"] if messages else payload.message),
            )
            message = ((response.get("choices") or [{}])[0]).get("message") or {}
            tool_calls = message.get("tool_calls") or []
            content = message.get("content")

            if tool_calls:
                messages.append({"role": "assistant", "content": content or "", "tool_calls": tool_calls})
                for tool_call in tool_calls:
                    function = tool_call.get("function") or {}
                    tool_name = function.get("name", "")
                    arguments = self._normalize_args(function.get("arguments", "{}"))
                    result = self._execute_tool(tool_name, arguments, user_id, payload.channel)
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.get("id"),
                            "name": tool_name,
                            "content": json.dumps(result, ensure_ascii=False),
                        }
                    )
                    last_tool_name = tool_name
                    last_tool_payload = arguments
                    last_tool_result = result
                continue

            reply = self._finalize_reply(content, last_tool_name, last_tool_result)
            intent = self._map_intent(last_tool_name)
            self._log(payload, intent, last_tool_name, last_tool_payload, reply)
            return {"intent": intent, "reply": reply, "tool_result": last_tool_result}

        reply = self._finalize_reply("", last_tool_name, last_tool_result)
        intent = self._map_intent(last_tool_name)
        self._log(payload, intent, last_tool_name, last_tool_payload, reply)
        return {"intent": intent, "reply": reply, "tool_result": last_tool_result}

    def _build_system_prompt(self, timezone: str) -> str:
        now = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %z")
        return (
            "你是一个提醒助手，负责帮助用户管理提醒事项。\n"
            f"当前用户时区偏好：{timezone}\n"
            f"当前服务器时间：{now}\n"
            "规则：\n"
            "1. 对于自然语言创建提醒，优先理解用户真实意图并直接调用工具。\n"
            "2. 像“明天下午3点”“今晚8点”“后天上午开会提醒我”这类表达，不要说缺少具体时间；你应该直接解析并创建提醒。\n"
            "3. 只有在时间真的无法唯一判断时才追问，例如仅说“周五提醒我”却没有说明上午/下午或具体事项。\n"
            "4. 修改、删除、延后、完成提醒时，如果无法唯一定位目标提醒，再请用户提供 reminder_id。\n"
            "5. 网页聊天默认优先使用 web 渠道；只有用户明确要求邮件提醒时，才使用 email。\n"
            "6. 如果用户用“标题运动，仅一次提醒，优先级常规”这种结构化描述，标题必须取标题字段，不能把优先级当成标题。\n"
            "7. 回复使用简洁自然的中文。\n"
        )

    def _tool_schemas_gemini(self) -> list[types.FunctionDeclaration]:
        return [
            types.FunctionDeclaration(
                name="create_reminder",
                description="创建新的提醒任务",
                parameters={
                    "type": "OBJECT",
                    "properties": {
                        "title": {"type": "STRING"},
                        "remind_time": {"type": "STRING"},
                        "content": {"type": "STRING", "nullable": True},
                        "repeat_type": {"type": "STRING", "nullable": True},
                        "repeat_value": {"type": "STRING", "nullable": True},
                        "priority": {"type": "STRING", "nullable": True},
                        "channel_type": {"type": "STRING", "nullable": True},
                        "source_text": {"type": "STRING", "nullable": True},
                    },
                    "required": ["title", "remind_time"],
                },
            ),
            types.FunctionDeclaration(
                name="list_reminders",
                description="查询用户提醒列表",
                parameters={
                    "type": "OBJECT",
                    "properties": {
                        "status": {"type": "STRING", "nullable": True},
                        "repeat_type": {"type": "STRING", "nullable": True},
                    },
                },
            ),
            types.FunctionDeclaration(
                name="update_reminder",
                description="修改提醒内容或时间",
                parameters={
                    "type": "OBJECT",
                    "properties": {
                        "reminder_id": {"type": "INTEGER"},
                        "title": {"type": "STRING", "nullable": True},
                        "content": {"type": "STRING", "nullable": True},
                        "next_remind_time": {"type": "STRING", "nullable": True},
                        "repeat_type": {"type": "STRING", "nullable": True},
                        "repeat_value": {"type": "STRING", "nullable": True},
                        "priority": {"type": "STRING", "nullable": True},
                        "channel_type": {"type": "STRING", "nullable": True},
                        "status": {"type": "STRING", "nullable": True},
                    },
                    "required": ["reminder_id"],
                },
            ),
            types.FunctionDeclaration(
                name="delete_reminder",
                description="删除指定提醒",
                parameters={"type": "OBJECT", "properties": {"reminder_id": {"type": "INTEGER"}}, "required": ["reminder_id"]},
            ),
            types.FunctionDeclaration(
                name="snooze_reminder",
                description="延后提醒",
                parameters={
                    "type": "OBJECT",
                    "properties": {"reminder_id": {"type": "INTEGER"}, "minutes": {"type": "INTEGER"}},
                    "required": ["reminder_id", "minutes"],
                },
            ),
            types.FunctionDeclaration(
                name="mark_done",
                description="将提醒标记为完成",
                parameters={"type": "OBJECT", "properties": {"reminder_id": {"type": "INTEGER"}}, "required": ["reminder_id"]},
            ),
        ]

    def _tool_schemas_openai(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "create_reminder",
                    "description": "创建新的提醒任务",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "remind_time": {"type": "string"},
                            "content": {"type": ["string", "null"]},
                            "repeat_type": {"type": ["string", "null"]},
                            "repeat_value": {"type": ["string", "null"]},
                            "priority": {"type": ["string", "null"]},
                            "channel_type": {"type": ["string", "null"]},
                            "source_text": {"type": ["string", "null"]},
                        },
                        "required": ["title", "remind_time"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "list_reminders",
                    "description": "查询用户提醒列表",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "status": {"type": ["string", "null"]},
                            "repeat_type": {"type": ["string", "null"]},
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "update_reminder",
                    "description": "修改提醒内容或时间",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "reminder_id": {"type": "integer"},
                            "title": {"type": ["string", "null"]},
                            "content": {"type": ["string", "null"]},
                            "next_remind_time": {"type": ["string", "null"]},
                            "repeat_type": {"type": ["string", "null"]},
                            "repeat_value": {"type": ["string", "null"]},
                            "priority": {"type": ["string", "null"]},
                            "channel_type": {"type": ["string", "null"]},
                            "status": {"type": ["string", "null"]},
                        },
                        "required": ["reminder_id"],
                    },
                },
            },
            {"type": "function", "function": {"name": "delete_reminder", "description": "删除指定提醒", "parameters": {"type": "object", "properties": {"reminder_id": {"type": "integer"}}, "required": ["reminder_id"]}}},
            {"type": "function", "function": {"name": "snooze_reminder", "description": "延后提醒", "parameters": {"type": "object", "properties": {"reminder_id": {"type": "integer"}, "minutes": {"type": "integer"}}, "required": ["reminder_id", "minutes"]}}},
            {"type": "function", "function": {"name": "mark_done", "description": "将提醒标记为完成", "parameters": {"type": "object", "properties": {"reminder_id": {"type": "integer"}}, "required": ["reminder_id"]}}},
        ]

    def _execute_tool(self, tool_name: str, arguments: dict[str, Any], user_id: int, fallback_channel: str = "web") -> dict[str, Any]:
        if tool_name == "create_reminder":
            arguments = self._normalize_create_arguments(arguments, fallback_channel)
            reminder = self.reminder_service.create_reminder(
                ReminderCreateRequest(
                    user_id=user_id,
                    title=arguments["title"],
                    content=arguments.get("content"),
                    source_text=arguments.get("source_text"),
                    remind_time=datetime.fromisoformat(arguments["remind_time"]),
                    repeat_type=arguments.get("repeat_type") or "none",
                    repeat_value=arguments.get("repeat_value"),
                    priority=arguments.get("priority") or "medium",
                    channel_type=arguments.get("channel_type") or fallback_channel or "web",
                )
            )
            return {"reminder_id": reminder.id, "title": reminder.title, "status": reminder.status, "next_remind_time": reminder.next_remind_time.isoformat()}

        if tool_name == "list_reminders":
            reminders = self.reminder_service.list_reminders(user_id=user_id, status=arguments.get("status"), repeat_type=arguments.get("repeat_type"))
            return {"count": len(reminders), "items": [{"id": item.id, "title": item.title, "status": item.status, "next_remind_time": item.next_remind_time.isoformat(), "repeat_type": item.repeat_type} for item in reminders[:20]]}

        if tool_name == "update_reminder":
            reminder = self.reminder_service.update_reminder(
                reminder_id=arguments["reminder_id"],
                payload=ReminderUpdateRequest(
                    title=arguments.get("title"),
                    content=arguments.get("content"),
                    next_remind_time=datetime.fromisoformat(arguments["next_remind_time"]) if arguments.get("next_remind_time") else None,
                    repeat_type=arguments.get("repeat_type"),
                    repeat_value=arguments.get("repeat_value"),
                    priority=arguments.get("priority"),
                    channel_type=arguments.get("channel_type"),
                    status=arguments.get("status"),
                ),
            )
            return {"reminder_id": reminder.id, "title": reminder.title, "status": reminder.status, "next_remind_time": reminder.next_remind_time.isoformat()}

        if tool_name == "delete_reminder":
            reminder = self.reminder_service.delete_reminder(arguments["reminder_id"])
            return {"reminder_id": reminder.id, "status": reminder.status, "is_deleted": reminder.is_deleted}

        if tool_name == "snooze_reminder":
            reminder = self.reminder_service.snooze_reminder(arguments["reminder_id"], arguments["minutes"])
            return {"reminder_id": reminder.id, "status": reminder.status, "next_remind_time": reminder.next_remind_time.isoformat()}

        if tool_name == "mark_done":
            reminder = self.reminder_service.mark_done(arguments["reminder_id"])
            return {"reminder_id": reminder.id, "status": reminder.status}

        raise HTTPException(status_code=400, detail=f"Unsupported tool: {tool_name}")

    def _try_local_action(self, payload: AgentChatRequest, user_id: int) -> dict[str, Any] | None:
        message = payload.message.strip()
        compact = re.sub(r"\s+", "", message)

        pending_plan_result = self._try_pending_plan_action(payload, user_id)
        if pending_plan_result is not None:
            return pending_plan_result

        pending_delete_result = self._try_pending_delete_action(payload, user_id)
        if pending_delete_result is not None:
            return pending_delete_result

        pending_change_result = self._try_pending_change_action(payload, user_id)
        if pending_change_result is not None:
            return pending_change_result

        cancel_result = self._try_humanized_delete(payload, user_id)
        if cancel_result is not None:
            return cancel_result

        update_result = self._try_humanized_update(payload, user_id)
        if update_result is not None:
            return update_result

        done_result = self._try_humanized_done(payload, user_id)
        if done_result is not None:
            return done_result

        snooze_result = self._try_humanized_snooze(payload, user_id)
        if snooze_result is not None:
            return snooze_result

        if self._looks_like_list_request(compact):
            result = self._execute_tool("list_reminders", {"status": None, "repeat_type": None}, user_id, payload.channel)
            return {
                "intent": "list_reminders",
                "reply": self._build_tool_reply("list_reminders", result) or "你当前没有符合条件的提醒。",
                "tool_payload": {"status": None, "repeat_type": None},
                "tool_result": result,
            }

        structured_payload = self._parse_structured_create_message(message, payload.channel)
        if structured_payload is not None:
            result = self._execute_tool("create_reminder", structured_payload, user_id, payload.channel)
            return {
                "intent": "create_reminder",
                "reply": self._build_tool_reply("create_reminder", result) or f"已为你创建提醒：{structured_payload['title']}。",
                "tool_payload": structured_payload,
                "tool_result": result,
            }

        return None

    def _try_humanized_delete(self, payload: AgentChatRequest, user_id: int) -> dict[str, Any] | None:
        compact = re.sub(r"\s+", "", payload.message or "")
        delete_words = ("取消", "删除", "删掉", "不要", "去掉")
        if not any(word in compact for word in delete_words):
            return None
        targets = self._resolve_reminder_targets(payload.message, user_id, payload.session_id, prefer_pending=True)
        if not targets:
            return {
                "intent": "delete_reminder",
                "reply": self._build_not_found_reply(payload.message, user_id, "取消"),
                "tool_payload": None,
                "tool_result": None,
            }

        session_key = self._pending_plan_key(user_id, payload.session_id)
        self.pending_delete_store[session_key] = {
            "targets": [{"id": item.id, "title": item.title, "next_remind_time": item.next_remind_time.isoformat()} for item in targets],
            "source_text": payload.message,
        }
        self._remember_conversation_targets(session_key, targets)

        if len(targets) == 1:
            reminder = targets[0]
            reply = (
                f"我找到 1 条要取消的提醒：\n"
                f"- #{reminder.id} {self._format_display_time(reminder.next_remind_time.isoformat())} {reminder.title}\n"
                "如果确认删除，请回复“确认删除”；如果不删，回复“取消删除”。"
            )
        else:
            reply = f"我找到 {len(targets)} 条可能要取消的提醒："
            preview = [
                f"- #{item.id} {self._format_display_time(item.next_remind_time.isoformat())} {item.title}"
                for item in targets[:8]
            ]
            if preview:
                reply += "\n" + "\n".join(preview)
            if len(targets) > 8:
                reply += f"\n另有 {len(targets) - 8} 条同批提醒。"
            reply += "\n如果确认删除，请回复“确认删除”；如果不删，回复“取消删除”。"

        return {
            "intent": "delete_confirm",
            "reply": reply,
            "tool_payload": {"reminder_ids": [item.id for item in targets]},
            "tool_result": {"count": len(targets), "items": [{"id": item.id, "title": item.title} for item in targets]},
        }

    def _try_humanized_done(self, payload: AgentChatRequest, user_id: int) -> dict[str, Any] | None:
        compact = re.sub(r"\s+", "", payload.message or "")
        done_words = ("完成", "做完", "搞定", "已完成", "结束")
        if not any(word in compact for word in done_words):
            return None
        targets = self._resolve_reminder_targets(payload.message, user_id, payload.session_id, prefer_pending=True)
        if not targets:
            return None

        reminder = targets[0]
        result = self._execute_tool("mark_done", {"reminder_id": reminder.id}, user_id, payload.channel)
        return {
            "intent": "mark_done",
            "reply": f"已将提醒 #{reminder.id} 标记为完成：{reminder.title}。",
            "tool_payload": {"reminder_id": reminder.id},
            "tool_result": result,
        }

    def _try_humanized_snooze(self, payload: AgentChatRequest, user_id: int) -> dict[str, Any] | None:
        compact = re.sub(r"\s+", "", payload.message or "")
        snooze_words = ("延后", "推迟", "晚点", "稍后", "顺延")
        if not any(word in compact for word in snooze_words):
            return None

        minute_match = re.search(r"(\d{1,3})\s*分", payload.message)
        minutes = int(minute_match.group(1)) if minute_match else 10
        targets = self._resolve_reminder_targets(payload.message, user_id, payload.session_id, prefer_pending=True)
        if not targets:
            return {
                "intent": "snooze_reminder",
                "reply": self._build_not_found_reply(payload.message, user_id, "延后"),
                "tool_payload": None,
                "tool_result": None,
            }

        reminder = targets[0]
        session_key = self._pending_plan_key(user_id, payload.session_id)
        self.pending_change_store[session_key] = {
            "action": "snooze",
            "target": {"id": reminder.id, "title": reminder.title, "next_remind_time": reminder.next_remind_time.isoformat()},
            "minutes": minutes,
        }
        self._remember_conversation_targets(session_key, [reminder])
        return {
            "intent": "snooze_confirm",
            "reply": (
                f"我找到要延后的提醒：\n"
                f"- #{reminder.id} {self._format_display_time(reminder.next_remind_time.isoformat())} {reminder.title}\n"
                f"准备延后 {minutes} 分钟。如果确认，请回复“确认修改”；如果不改，回复“取消修改”。"
            ),
            "tool_payload": {"reminder_id": reminder.id, "minutes": minutes},
            "tool_result": {"reminder_id": reminder.id, "title": reminder.title, "minutes": minutes},
        }

    def _try_humanized_update(self, payload: AgentChatRequest, user_id: int) -> dict[str, Any] | None:
        compact = re.sub(r"\s+", "", payload.message or "")
        update_words = ("改到", "改成", "改为", "改一下", "调整到", "挪到")
        if not any(word in compact for word in update_words):
            return None
        targets = self._resolve_reminder_targets(payload.message, user_id, payload.session_id, prefer_pending=True)
        if not targets:
            return {
                "intent": "update_reminder",
                "reply": self._build_not_found_reply(payload.message, user_id, "修改"),
                "tool_payload": None,
                "tool_result": None,
            }

        user = self.user_repo.get_by_id(user_id)
        new_time = self._parse_natural_remind_time(payload.message, user.timezone)
        if not new_time:
            return {
                "intent": "update_reminder",
                "reply": "我找到目标提醒了，但还没看懂你想改到几点。你可以直接说“改到 8 点半”或“改到明天上午 9 点”。",
                "tool_payload": {"reminder_id": targets[0].id},
                "tool_result": None,
            }

        reminder = targets[0]
        if not self._message_has_absolute_day_reference(payload.message):
            preserved = self._merge_time_into_existing_reminder(reminder.next_remind_time, new_time, user.timezone)
            if preserved:
                new_time = preserved
        session_key = self._pending_plan_key(user_id, payload.session_id)
        self.pending_change_store[session_key] = {
            "action": "update_time",
            "target": {"id": reminder.id, "title": reminder.title, "next_remind_time": reminder.next_remind_time.isoformat()},
            "next_remind_time": new_time,
        }
        self._remember_conversation_targets(session_key, [reminder])
        return {
            "intent": "update_confirm",
            "reply": (
                f"我找到要修改的提醒：\n"
                f"- #{reminder.id} {self._format_display_time(reminder.next_remind_time.isoformat())} {reminder.title}\n"
                f"准备改到 {self._format_display_time(new_time)}。如果确认，请回复“确认修改”；如果不改，回复“取消修改”。"
            ),
            "tool_payload": {"reminder_id": reminder.id, "next_remind_time": new_time},
            "tool_result": {"reminder_id": reminder.id, "title": reminder.title, "next_remind_time": new_time},
        }

    def _try_pending_plan_action(self, payload: AgentChatRequest, user_id: int) -> dict[str, Any] | None:
        session_key = self._pending_plan_key(user_id, payload.session_id)
        pending_plan = self.pending_plan_store.get(session_key)
        if not pending_plan:
            return None

        compact = re.sub(r"\s+", "", payload.message or "")
        if compact in {"确认", "好的确认", "确认创建", "确认一下", "就按这个来", "按这个来", "可以"}:
            created_items: list[dict[str, Any]] = []
            for spec in pending_plan.get("reminders", []):
                if not isinstance(spec, dict):
                    continue
                tool_payload = {
                    "title": spec.get("title"),
                    "content": spec.get("content"),
                    "source_text": pending_plan.get("source_text") or payload.message,
                    "remind_time": spec.get("remind_time"),
                    "repeat_type": spec.get("repeat_type") or "none",
                    "repeat_value": spec.get("repeat_value"),
                    "priority": spec.get("priority") or "medium",
                    "channel_type": spec.get("channel_type") or payload.channel,
                }
                if not tool_payload["title"] or not tool_payload["remind_time"]:
                    continue
                created_items.append(self._execute_tool("create_reminder", tool_payload, user_id, payload.channel))

            self.pending_plan_store.pop(session_key, None)
            if not created_items:
                return {
                    "intent": "plan_confirm",
                    "reply": "这份草案里没有可创建的提醒，我先没有写入数据库。你可以换个说法让我重新规划。",
                    "tool_payload": pending_plan,
                    "tool_result": {"count": 0, "items": []},
                }

            lines = [f"已按草案为你创建 {len(created_items)} 条提醒："]
            for item in created_items[:5]:
                lines.append(f"- {self._format_display_time(item.get('next_remind_time'))} {item.get('title') or '未命名提醒'}")
            if len(created_items) > 5:
                lines.append("其余提醒也已经一并创建。")
            return {
                "intent": "plan_confirm",
                "reply": "\n".join(lines),
                "tool_payload": pending_plan,
                "tool_result": {"count": len(created_items), "items": created_items},
            }

        if compact in {"取消", "不用了", "先取消", "不创建了", "算了"}:
            self.pending_plan_store.pop(session_key, None)
            return {
                "intent": "plan_cancel",
                "reply": "好的，这份提醒草案我先取消了，没有写入数据库。你想重新规划时再告诉我。",
                "tool_payload": pending_plan,
                "tool_result": None,
            }

        return None

    def _try_pending_delete_action(self, payload: AgentChatRequest, user_id: int) -> dict[str, Any] | None:
        session_key = self._pending_plan_key(user_id, payload.session_id)
        pending_delete = self.pending_delete_store.get(session_key)
        if not pending_delete:
            return None

        compact = re.sub(r"\s+", "", payload.message or "")
        if compact in {"确认删除", "确认", "删除", "确定删除", "是的删除"}:
            deleted = []
            for target in pending_delete.get("targets", []):
                reminder_id = target.get("id")
                if not reminder_id:
                    continue
                try:
                    result = self._execute_tool("delete_reminder", {"reminder_id": reminder_id}, user_id, payload.channel)
                except HTTPException:
                    continue
                deleted.append({"id": reminder_id, "title": target.get("title"), "result": result})
            self.pending_delete_store.pop(session_key, None)
            if not deleted:
                return {
                    "intent": "delete_reminder",
                    "reply": "这批提醒看起来已经不存在或已经被处理了，所以我没有再删除到任何记录。",
                    "tool_payload": pending_delete,
                    "tool_result": {"count": 0, "items": []},
                }
            if len(deleted) == 1:
                reply = f"已为你取消提醒 #{deleted[0]['id']}：{deleted[0]['title']}。"
            else:
                reply = f"已为你取消这批提醒，共 {len(deleted)} 条。"
                preview = [f"#{item['id']} {item['title']}" for item in deleted[:5]]
                if preview:
                    reply += "\n" + "\n".join(preview)
                if len(deleted) > 5:
                    reply += "\n其余提醒也已一并取消。"
            return {
                "intent": "delete_reminder",
                "reply": reply,
                "tool_payload": {"reminder_ids": [item["id"] for item in deleted]},
                "tool_result": {"count": len(deleted), "items": deleted},
            }

        if compact in {"取消删除", "先别删", "不删了", "算了", "取消"}:
            self.pending_delete_store.pop(session_key, None)
            return {
                "intent": "delete_cancel",
                "reply": "好的，这次删除我先取消，不会改动你的提醒。",
                "tool_payload": pending_delete,
                "tool_result": None,
            }

        return None

    def _try_pending_change_action(self, payload: AgentChatRequest, user_id: int) -> dict[str, Any] | None:
        session_key = self._pending_plan_key(user_id, payload.session_id)
        pending_change = self.pending_change_store.get(session_key)
        if not pending_change:
            return None

        compact = re.sub(r"\s+", "", payload.message or "")
        if compact in {"确认修改", "确认", "确定修改", "是的修改"}:
            target = pending_change.get("target") or {}
            reminder_id = target.get("id")
            if not reminder_id:
                self.pending_change_store.pop(session_key, None)
                return None

            try:
                existing = self.reminder_service.get_reminder(reminder_id)
            except HTTPException:
                self.pending_change_store.pop(session_key, None)
                return {
                    "intent": "change_missing",
                    "reply": "这条提醒已经不存在了，可能刚刚已经被删除或完成，所以这次修改没有执行。",
                    "tool_payload": pending_change,
                    "tool_result": None,
                }

            action = pending_change.get("action")
            if action == "snooze":
                result = self._execute_tool(
                    "snooze_reminder",
                    {"reminder_id": reminder_id, "minutes": pending_change.get("minutes", 10)},
                    user_id,
                    payload.channel,
                )
                self.pending_change_store.pop(session_key, None)
                self._remember_conversation_targets(session_key, [existing])
                return {
                    "intent": "snooze_reminder",
                    "reply": f"已将提醒 #{existing.id} 延后 {pending_change.get('minutes', 10)} 分钟：{existing.title}。",
                    "tool_payload": {"reminder_id": existing.id, "minutes": pending_change.get("minutes", 10)},
                    "tool_result": result,
                }

            if action == "update_time":
                result = self._execute_tool(
                    "update_reminder",
                    {"reminder_id": reminder_id, "next_remind_time": pending_change.get("next_remind_time")},
                    user_id,
                    payload.channel,
                )
                self.pending_change_store.pop(session_key, None)
                self._remember_conversation_targets(session_key, [self.reminder_service.get_reminder(reminder_id)])
                return {
                    "intent": "update_reminder",
                    "reply": f"已将提醒 #{existing.id} 修改为 {self._format_display_time(pending_change.get('next_remind_time'))}：{existing.title}。",
                    "tool_payload": {"reminder_id": existing.id, "next_remind_time": pending_change.get("next_remind_time")},
                    "tool_result": result,
                }

            self.pending_change_store.pop(session_key, None)
            return None

        if compact in {"取消修改", "不改了", "先别改", "算了", "取消"}:
            target = pending_change.get("target") or {}
            reminder_id = target.get("id")
            if reminder_id:
                try:
                    existing = self.reminder_service.get_reminder(reminder_id)
                    self._remember_conversation_targets(session_key, [existing])
                except HTTPException:
                    pass
            self.pending_change_store.pop(session_key, None)
            return {
                "intent": "change_cancel",
                "reply": "好的，这次修改我先取消，不会改动你的提醒。",
                "tool_payload": pending_change,
                "tool_result": None,
            }

        return None

    def _looks_like_list_request(self, compact_message: str) -> bool:
        keywords = ("查看", "看看", "查询", "列出", "显示", "有哪些", "我的提醒", "提醒列表")
        if "提醒" not in compact_message:
            return False
        for keyword in keywords:
            if keyword in compact_message:
                return True
        return False

    def _parse_structured_create_message(self, message: str, channel: str) -> dict[str, Any] | None:
        title = self._extract_structured_title(message)
        remind_time = self._extract_structured_time(message)
        if not title or not remind_time:
            return None
        return {
            "title": title,
            "content": None,
            "source_text": message,
            "remind_time": remind_time,
            "repeat_type": self._normalize_repeat_type(None, message),
            "repeat_value": None,
            "priority": self._extract_structured_priority(message) or "medium",
            "channel_type": channel or "web",
        }

    def _normalize_create_arguments(self, arguments: dict[str, Any], fallback_channel: str) -> dict[str, Any]:
        normalized = dict(arguments)
        source_text = str(normalized.get("source_text") or "").strip()
        current_title = str(normalized.get("title") or "").strip()
        extracted_title = self._extract_structured_title(source_text)
        if extracted_title and (not current_title or current_title in {"优先级常规", "优先级一般", "常规", "一般", "medium"}):
            normalized["title"] = extracted_title
        normalized["priority"] = self._extract_structured_priority(source_text) or normalized.get("priority") or "medium"
        extracted_time = self._extract_structured_time(source_text)
        if extracted_time:
            normalized["remind_time"] = extracted_time
        normalized["repeat_type"] = self._normalize_repeat_type(normalized.get("repeat_type"), source_text)
        normalized["channel_type"] = str(normalized.get("channel_type") or fallback_channel or "web").lower()
        normalized["content"] = normalized.get("content") or None
        repeat_value = normalized.get("repeat_value")
        if isinstance(repeat_value, (list, dict)):
            normalized["repeat_value"] = json.dumps(repeat_value, ensure_ascii=False)
        else:
            normalized["repeat_value"] = repeat_value or None
        normalized["source_text"] = source_text or None
        return normalized

    def _extract_structured_title(self, message: str) -> str:
        match = re.search(r"标题[:：]?\s*([^，。,；;]+)", message)
        return match.group(1).strip() if match else ""

    def _extract_structured_priority(self, message: str) -> str | None:
        match = re.search(r"优先级[:：]?\s*([^，。,；;]+)", message)
        if not match:
            return None
        mapping = {"高": "high", "高优先级": "high", "high": "high", "紧急": "high", "常规": "medium", "一般": "medium", "中": "medium", "medium": "medium", "低": "low", "low": "low"}
        return mapping.get(match.group(1).strip().lower(), "medium")

    def _normalize_repeat_type(self, repeat_type: Any, source_text: str) -> str:
        raw = str(repeat_type or "").strip().lower()
        if raw in {"none", "daily", "weekly", "monthly"}:
            return raw
        if any(token in source_text for token in ("仅一次", "一次", "不重复")):
            return "none"
        if "每天" in source_text:
            return "daily"
        if "每周" in source_text:
            return "weekly"
        if "每月" in source_text:
            return "monthly"
        return "none"

    def _extract_structured_time(self, message: str) -> str | None:
        absolute_match = re.search(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日\s*(\d{1,2})\s*点(?:\s*(\d{1,2})\s*分)?", message)
        if absolute_match:
            year, month, day, hour, minute = absolute_match.groups()
            dt = datetime(int(year), int(month), int(day), int(hour), int(minute or 0))
            return f"{dt.strftime('%Y-%m-%dT%H:%M:%S')}+08:00"
        relative_match = re.search(r"(今天|明天|后天)\s*(\d{1,2})\s*点(?:\s*(\d{1,2})\s*分)?", message)
        if relative_match:
            day_text, hour, minute = relative_match.groups()
            offset = {"今天": 0, "明天": 1, "后天": 2}[day_text]
            dt = datetime.now().replace(hour=int(hour), minute=int(minute or 0), second=0, microsecond=0) + timedelta(days=offset)
            return f"{dt.strftime('%Y-%m-%dT%H:%M:%S')}+08:00"
        return None

    def _map_intent(self, tool_name: str | None) -> str:
        return tool_name or "chat"

    def _choose_modelscope_tool(self, message: str) -> str | dict[str, Any]:
        compact = re.sub(r"\s+", "", message or "")
        if "提醒" in compact and not self._looks_like_list_request(compact):
            return {"type": "function", "function": {"name": "create_reminder"}}
        return "auto"

    async def _try_model_plan_create(self, payload: AgentChatRequest, timezone: str, user_id: int) -> dict[str, Any] | None:
        if not self._looks_like_plan_request(payload.message):
            return None

        extracted = None
        if self.gemini_service.is_configured:
            try:
                extracted = await self._extract_plan_json_with_gemini(payload.message, timezone, payload.channel)
            except errors.ClientError as exc:
                if not self._should_fallback_to_modelscope(exc):
                    return None
            except Exception:
                pass

        if extracted is None and self.modelscope_service.is_configured:
            try:
                extracted = await self._extract_plan_json_with_modelscope(payload.message, timezone, payload.channel)
            except Exception:
                return None

        if not extracted:
            return None

        if extracted.get("need_follow_up"):
            return {
                "intent": "plan_reminders",
                "reply": extracted.get("reply") or "我还需要补充一点信息，才能帮你自动安排提醒。",
                "tool_payload": extracted,
                "tool_result": None,
            }

        reminder_specs = extracted.get("reminders") or []
        if not isinstance(reminder_specs, list) or not reminder_specs:
            return None

        normalized_specs: list[dict[str, Any]] = []
        for spec in reminder_specs:
            if not isinstance(spec, dict):
                continue
            normalized = {
                "title": spec.get("title"),
                "content": spec.get("content"),
                "source_text": payload.message,
                "remind_time": spec.get("remind_time"),
                "repeat_type": spec.get("repeat_type") or "none",
                "repeat_value": spec.get("repeat_value"),
                "priority": spec.get("priority") or "medium",
                "channel_type": spec.get("channel_type") or payload.channel,
            }
            if not normalized["title"] or not normalized["remind_time"]:
                continue
            normalized_specs.append(normalized)

        if not normalized_specs:
            return None

        normalized_specs = self._expand_weekly_plan_specs(payload.message, normalized_specs, timezone)

        session_key = self._pending_plan_key(user_id, payload.session_id)
        self.pending_plan_store[session_key] = {
            "summary": extracted.get("summary"),
            "reply": extracted.get("reply"),
            "reminders": normalized_specs,
            "source_text": payload.message,
            "created_at": datetime.now().isoformat(),
        }

        summary = str(extracted.get("summary") or "").strip()
        reply_lines = [summary] if summary else []
        reply_lines.append(f"我先帮你整理出 {len(normalized_specs)} 条提醒草案：")
        reply_lines.extend(self._format_plan_draft_lines(normalized_specs))
        reply_lines.append("上方会出现“确认创建”和“取消草案”按钮。")

        return {
            "intent": "plan_draft",
            "reply": "\n".join(reply_lines),
            "tool_payload": extracted,
            "tool_result": {"count": len(normalized_specs), "items": normalized_specs},
        }

    def _looks_like_plan_request(self, message: str) -> bool:
        compact = re.sub(r"\s+", "", message or "")
        planner_words = ("安排", "规划", "计划", "作息", "日程", "习惯", "生活节奏", "一日三餐", "健身", "早餐", "午饭", "晚饭", "睡觉", "起床")
        reminder_words = ("提醒", "监督", "打卡", "安排我", "帮我设置")
        has_planner_word = False
        for word in planner_words:
            if word in compact:
                has_planner_word = True
                break
        if not has_planner_word:
            return False
        for word in reminder_words:
            if word in compact:
                return True
        return "帮我" in compact or "给我" in compact

    def _pending_plan_key(self, user_id: int, session_id: str | None) -> str:
        return f"{user_id}:{(session_id or 'default').strip() or 'default'}"

    def _is_weekly_plan_request(self, message: str) -> bool:
        compact = re.sub(r"\s+", "", message or "")
        weekly_terms = ("一周", "下一周", "下周", "本周", "这周", "周计划", "周日程")
        for term in weekly_terms:
            if term in compact:
                return True
        return False

    def _expand_weekly_plan_specs(self, message: str, specs: list[dict[str, Any]], timezone: str) -> list[dict[str, Any]]:
        if not self._is_weekly_plan_request(message):
            return specs
        if len(specs) >= 10:
            return specs

        tz = ZoneInfo(timezone or "Asia/Shanghai")
        start_day = self._resolve_week_start(message, tz)
        if start_day is None:
            return specs

        daily_templates: list[dict[str, Any]] = []
        one_off_templates: list[dict[str, Any]] = []
        for spec in specs:
            title = str(spec.get("title") or "")
            if "每周" in title or "每周" in str(spec.get("content") or ""):
                one_off_templates.append(spec)
                continue
            daily_templates.append(spec)

        if not daily_templates:
            return specs

        daily_templates = daily_templates[:3]
        expanded: list[dict[str, Any]] = []
        for day_index in range(7):
            target_date = start_day + timedelta(days=day_index)
            for template in daily_templates:
                expanded.append(self._clone_plan_spec_for_day(template, target_date))

        for index, template in enumerate(one_off_templates):
            target_date = start_day + timedelta(days=min(index + 5, 6))
            expanded.append(self._clone_plan_spec_for_day(template, target_date))

        return expanded

    def _resolve_week_start(self, message: str, tz: ZoneInfo) -> datetime | None:
        compact = re.sub(r"\s+", "", message or "")
        now = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
        weekday = now.weekday()
        if "下一周" in compact or "下周" in compact:
            days_until_next_monday = (7 - weekday) % 7
            if days_until_next_monday == 0:
                days_until_next_monday = 7
            return now + timedelta(days=days_until_next_monday)
        if "本周" in compact or "这周" in compact or "一周" in compact or "周计划" in compact or "周日程" in compact:
            return now - timedelta(days=weekday)
        return None

    def _clone_plan_spec_for_day(self, spec: dict[str, Any], target_date: datetime) -> dict[str, Any]:
        cloned = dict(spec)
        remind_time = str(spec.get("remind_time") or "").strip()
        try:
            source_dt = datetime.fromisoformat(remind_time)
        except ValueError:
            return cloned
        cloned["remind_time"] = source_dt.replace(
            year=target_date.year,
            month=target_date.month,
            day=target_date.day,
        ).isoformat()
        return cloned

    def _format_plan_draft_lines(self, specs: list[dict[str, Any]]) -> list[str]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        ordered_dates: list[str] = []
        for spec in specs:
            remind_time = str(spec.get("remind_time") or "")
            try:
                dt = datetime.fromisoformat(remind_time)
                date_key = dt.strftime("%Y-%m-%d")
                time_text = dt.strftime("%H:%M")
            except ValueError:
                date_key = "未解析日期"
                time_text = remind_time or "未设置时间"
            grouped.setdefault(date_key, []).append({"time": time_text, "title": spec.get("title") or "未命名提醒"})
            if date_key not in ordered_dates:
                ordered_dates.append(date_key)

        lines: list[str] = []
        for date_key in ordered_dates:
            lines.append(f"{date_key}:")
            for item in grouped.get(date_key, []):
                lines.append(f"- {item['time']} {item['title']}")
        remaining_days = 0
        if remaining_days > 0:
            lines.append(f"另有 {remaining_days} 天的草案已一并整理。")
        return lines

    def _sanitize_plan_summary(self, summary: str) -> str:
        text = (summary or "").strip()
        if not text:
            return ""

        patterns = [
            r"共(?:整理出|设定|安排|生成)?\s*[0-9一二三四五六七八九十百零两]+\s*(?:个)?(?:关键节点|条提醒|条待确认的提醒|项安排)",
            r"下面是\s*[0-9一二三四五六七八九十百零两]+\s*条待确认的提醒",
        ]
        for pattern in patterns:
            text = re.sub(pattern, "", text)

        return re.sub(r"[，、；：]\s*$", "", text).strip()

    def _resolve_reminder_targets(self, message: str, user_id: int, session_id: str | None = None, prefer_pending: bool = True) -> list[Any]:
        id_matches = self._extract_explicit_reminder_ids(message)
        if id_matches:
            resolved = []
            for reminder_id in id_matches:
                try:
                    reminder = self.reminder_service.get_reminder(reminder_id)
                except HTTPException:
                    continue
                if reminder.user_id == user_id:
                    resolved.append(reminder)
            if resolved:
                return resolved

        recent = self.reminder_service.list_recent_reminders(user_id=user_id, limit=50, include_finished=not prefer_pending)
        if prefer_pending:
            recent = [item for item in recent if item.status == "pending"]
        if not recent:
            return []

        compact = re.sub(r"\s+", "", message or "")
        weekday_index = self._extract_weekday_index(compact)

        if any(token in compact for token in ("刚刚", "刚才", "最新", "上一条", "最近", "那个日程", "这批", "这组")):
            batch = self._latest_batch_from_recent(recent)
            if batch:
                if "周" in compact or "日程" in compact or "计划" in compact:
                    weekly_batch = [item for item in batch if self._is_weekly_plan_text(item.source_text or "")]
                    return weekly_batch or batch
                return batch

        if "下一周" in compact or "下周" in compact or "一周" in compact or "周日程" in compact or "周计划" in compact:
            weekly_items = [item for item in recent if self._is_weekly_plan_text(item.source_text or "")]
            if weekly_items:
                return self._latest_batch_from_recent(weekly_items)

        keyword = self._extract_reminder_keyword(message)
        if weekday_index is not None:
            weekday_matches = [item for item in recent if item.next_remind_time.weekday() == weekday_index]
            if keyword:
                narrowed = [item for item in weekday_matches if self._reminder_matches_keyword(item, keyword)]
                if narrowed:
                    return self._latest_batch_from_recent(narrowed)
                return []
            if weekday_matches:
                return weekday_matches[:1]

        if keyword:
            matches = [item for item in recent if self._reminder_matches_keyword(item, keyword)]
            if matches:
                return self._latest_batch_from_recent(matches)
            return []

        if session_id:
            session_key = self._pending_plan_key(user_id, session_id)
            contextual = self._get_contextual_targets(session_key, user_id, prefer_pending)
            if contextual and self._looks_like_followup_message(message):
                return contextual

        if any(token in compact for token in ("第一个", "最早")):
            ordered = sorted(recent, key=lambda item: item.next_remind_time)
            return ordered[:1]

        return recent[:1]

    def _extract_explicit_reminder_ids(self, message: str) -> list[int]:
        text = message or ""
        matches: list[int] = []
        for pattern in (r"#(\d+)", r"\bid[:：]?\s*(\d+)\b", r"提醒\s*#?(\d+)"):
            for value in re.findall(pattern, text, flags=re.IGNORECASE):
                try:
                    matches.append(int(value))
                except ValueError:
                    continue
        deduped: list[int] = []
        for value in matches:
            if value not in deduped:
                deduped.append(value)
        return deduped

    def _remember_conversation_targets(self, session_key: str, reminders: list[Any]) -> None:
        if not reminders:
            return
        self.conversation_target_store[session_key] = {
            "reminder_ids": [item.id for item in reminders if getattr(item, "id", None)],
            "saved_at": datetime.now().isoformat(),
        }

    def _get_contextual_targets(self, session_key: str, user_id: int, prefer_pending: bool) -> list[Any]:
        stored = self.conversation_target_store.get(session_key)
        if not stored:
            return []
        resolved = []
        for reminder_id in stored.get("reminder_ids", []):
            try:
                reminder = self.reminder_service.get_reminder(reminder_id)
            except HTTPException:
                continue
            if reminder.user_id != user_id:
                continue
            if prefer_pending and reminder.status != "pending":
                continue
            resolved.append(reminder)
        return resolved

    def _looks_like_followup_message(self, message: str) -> bool:
        compact = re.sub(r"\s+", "", message or "")
        followup_words = ("改到", "改成", "改为", "调整到", "延后", "推迟", "晚点", "取消修改", "确认修改", "确认删除", "取消删除", "删除", "取消")
        if any(word in compact for word in followup_words):
            return True
        if "改" in compact:
            return True
        if re.search(r"\d+\s*点(?:半|\d+\s*分?)?", compact):
            return True
        if re.search(r"\d+\s*分钟?", compact):
            return True
        return False

    def _build_not_found_reply(self, message: str, user_id: int, action: str) -> str:
        compact = re.sub(r"\s+", "", message or "")
        keyword = self._extract_reminder_keyword(message)
        weekday_index = self._extract_weekday_index(compact)
        all_recent = self.reminder_service.list_recent_reminders(user_id=user_id, limit=80, include_finished=True)

        if weekday_index is not None and keyword:
            all_matches = [
                item for item in all_recent
                if item.next_remind_time.weekday() == weekday_index and self._reminder_matches_keyword(item, keyword)
            ]
            weekday_name = self._weekday_name(weekday_index)
            if all_matches:
                latest = all_matches[0]
                if latest.is_deleted or latest.status in {"cancelled", "done"}:
                    return (
                        f"我没有找到待处理中的“{weekday_name}{keyword}”提醒。"
                        f"不过我看到你之前有一条同类提醒，当前状态是 {latest.status}。"
                        f"你是想重新创建一条新的 {weekday_name}{keyword} 提醒，还是其实想{action}别的那条？"
                    )
            return f"我没有找到待处理中的“{weekday_name}{keyword}”提醒。你是想重新创建一条，还是你其实想{action}周四或别的那条提醒？"

        if keyword:
            all_matches = [item for item in all_recent if self._reminder_matches_keyword(item, keyword)]
            if all_matches:
                latest = all_matches[0]
                if latest.is_deleted or latest.status in {"cancelled", "done"}:
                    return f"我找到过一条和“{keyword}”相关的提醒，但它现在已经是 {latest.status}。你是想重新创建一条新的提醒吗？"
            return f"我还没准确定位到你要{action}的是哪条提醒。你可以说得更具体一点，比如“把周三的早餐提醒改到 8 点半”或“把交论文初稿那个提醒延后 20 分钟”。"

        return f"我还没准确定位到你要{action}的是哪条提醒。你可以再补充一下目标提醒的日期或标题。"

    def _weekday_name(self, weekday_index: int) -> str:
        names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        if 0 <= weekday_index < len(names):
            return names[weekday_index]
        return "这一天"

    def _latest_batch_from_recent(self, reminders: list[Any]) -> list[Any]:
        if not reminders:
            return []
        latest = reminders[0]
        latest_source = (latest.source_text or "").strip()
        if latest_source:
            same_source = [item for item in reminders if (item.source_text or "").strip() == latest_source]
            if same_source:
                return same_source

        latest_created = latest.created_at
        batch = []
        for item in reminders:
            if item.created_at == latest_created:
                batch.append(item)
        return batch or [latest]

    def _extract_reminder_keyword(self, message: str) -> str:
        compact = re.sub(r"\s+", "", message or "")
        direct_match = re.search(r"(?:把|将)?(.+?)(?:那个|这个)?提醒", compact)
        if direct_match:
            candidate = direct_match.group(1).strip()
            candidate = re.sub(r"(周一|周二|周三|周四|周五|周六|周日|周天|星期一|星期二|星期三|星期四|星期五|星期六|星期日|星期天)", "", candidate)
            candidate = re.sub(r"^(取消|删除|把|将)", "", candidate)
            candidate = re.sub(r"^的", "", candidate)
            candidate = re.sub(r"(的)$", "", candidate)
            if len(candidate) >= 2:
                return candidate
        normalized = re.sub(r"[，。！？；,.;!?]", " ", compact)
        normalized = re.sub(r"(取消|删除|删掉|不要|去掉|完成|做完|搞定|已完成|结束|延后|推迟|晚点|稍后|顺延)", " ", normalized)
        normalized = re.sub(r"(提醒|日程|计划|这个|那个|刚刚|刚才|最新|上一条|最近|一下|一下子|删除前|确认删除|取消删除)", " ", normalized)
        normalized = re.sub(r"(下一周|下周|一周|周日程|周计划|周一|周二|周三|周四|周五|周六|周日|周天|星期一|星期二|星期三|星期四|星期五|星期六|星期日|星期天)", " ", normalized)
        normalized = re.sub(r"的", " ", normalized)
        normalized = re.sub(r"^(把|将|把这条|把那个|把这个)", " ", normalized)
        normalized = re.sub(r"\d+\s*分钟?", " ", normalized)
        normalized = re.sub(r"\d+\s*点(?:半|\d+\s*分?)?", " ", normalized)
        parts = [part.strip() for part in normalized.split() if part.strip()]
        for part in parts:
            part = re.sub(r"^(把|将)", "", part).strip()
            part = re.sub(r"^的", "", part).strip()
            part = re.sub(r"(那个|这个)$", "", part).strip()
            if len(part) >= 2:
                return part
        return ""

    def _extract_weekday_index(self, compact: str) -> int | None:
        mapping = {
            "周一": 0,
            "星期一": 0,
            "周二": 1,
            "星期二": 1,
            "周三": 2,
            "星期三": 2,
            "周四": 3,
            "星期四": 3,
            "周五": 4,
            "星期五": 4,
            "周六": 5,
            "星期六": 5,
            "周日": 6,
            "周天": 6,
            "星期日": 6,
            "星期天": 6,
        }
        for token, index in mapping.items():
            if token in compact:
                return index
        return None

    def _reminder_matches_keyword(self, reminder: Any, keyword: str) -> bool:
        haystacks = [
            str(reminder.title or ""),
            str(reminder.source_text or ""),
            str(reminder.content or ""),
        ]
        return any(keyword in haystack for haystack in haystacks)

    def _message_has_absolute_day_reference(self, message: str) -> bool:
        compact = re.sub(r"\s+", "", message or "")
        explicit_terms = (
            "今天", "明天", "后天", "大后天", "今晚", "今早", "今晨", "今下午",
            "明早", "明晨",
        )
        if re.search(r"\d{4}年\d{1,2}月\d{1,2}日", compact):
            return True
        return any(term in compact for term in explicit_terms)

    def _merge_time_into_existing_reminder(self, existing_time: datetime, parsed_time_text: str, timezone: str) -> str | None:
        try:
            parsed_dt = datetime.fromisoformat(parsed_time_text)
        except ValueError:
            return None
        if parsed_dt.tzinfo is None:
            parsed_dt = parsed_dt.replace(tzinfo=ZoneInfo(timezone or "Asia/Shanghai"))
        base = existing_time
        if base.tzinfo is None:
            base = base.replace(tzinfo=ZoneInfo(timezone or "Asia/Shanghai"))
        merged = base.replace(hour=parsed_dt.hour, minute=parsed_dt.minute, second=0, microsecond=0)
        return merged.isoformat()

    def _is_weekly_plan_text(self, text: str) -> bool:
        compact = re.sub(r"\s+", "", text or "")
        weekly_terms = ("一周", "下一周", "下周", "本周", "这周", "周计划", "周日程")
        for term in weekly_terms:
            if term in compact:
                return True
        return False

    async def _try_model_json_create(self, payload: AgentChatRequest, timezone: str, user_id: int) -> dict[str, Any] | None:
        if not self._looks_like_create_request(payload.message):
            return None

        extracted = None
        if self.gemini_service.is_configured:
            try:
                extracted = await self._extract_create_json_with_gemini(payload.message, timezone, payload.channel)
            except errors.ClientError as exc:
                if not self._should_fallback_to_modelscope(exc):
                    return None
            except Exception:
                pass

        if extracted is None and self.modelscope_service.is_configured:
            try:
                extracted = await self._extract_create_json_with_modelscope(payload.message, timezone, payload.channel)
            except Exception:
                return None

        if not extracted:
            return None

        extracted = self._recover_create_json(extracted, payload.message, timezone, payload.channel)

        if extracted.get("need_follow_up"):
            return {"intent": "chat", "reply": extracted.get("reply") or "我还需要补充一点信息，才能帮你创建提醒。", "tool_payload": extracted, "tool_result": None}

        if extracted.get("intent") != "create_reminder":
            return None

        tool_payload = {
            "title": extracted.get("title"),
            "content": extracted.get("content"),
            "source_text": payload.message,
            "remind_time": extracted.get("remind_time"),
            "repeat_type": extracted.get("repeat_type") or "none",
            "repeat_value": extracted.get("repeat_value"),
            "priority": extracted.get("priority") or "medium",
            "channel_type": extracted.get("channel_type") or payload.channel,
        }
        if not tool_payload["title"] or not tool_payload["remind_time"]:
            return None
        result = self._execute_tool("create_reminder", tool_payload, user_id, payload.channel)
        return {"intent": "create_reminder", "reply": self._build_tool_reply("create_reminder", result) or "已为你创建提醒。", "tool_payload": tool_payload, "tool_result": result}

    def _looks_like_create_request(self, message: str) -> bool:
        compact = re.sub(r"\s+", "", message or "")
        time_words = ("今天", "明天", "后天", "今晚", "下午", "上午", "早上", "晚上", "点", "分", "号", "月", "日")
        if "提醒" not in compact:
            return False
        for word in time_words:
            if word in compact:
                return True
        return False

    async def _extract_create_json_with_gemini(self, message: str, timezone: str, channel: str) -> dict[str, Any] | None:
        prompt = self._build_json_extraction_prompt(message, timezone, channel)
        response = await self.gemini_service.client.aio.models.generate_content(
            model=self.settings.gemini_model,
            contents=prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0),
        )
        return self._parse_json_object(getattr(response, "text", ""))

    async def _extract_create_json_with_modelscope(self, message: str, timezone: str, channel: str) -> dict[str, Any] | None:
        prompt = self._build_json_extraction_prompt(message, timezone, channel)
        response = await self.modelscope_service.create_chat_completion(
            messages=[
                {"role": "system", "content": "你是提醒助手，只输出一个 JSON 对象，不要输出任何额外说明。"},
                {"role": "user", "content": prompt},
            ],
            tools=None,
        )
        content = ((response.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        return self._parse_json_object(content)

    async def _extract_plan_json_with_gemini(self, message: str, timezone: str, channel: str) -> dict[str, Any] | None:
        prompt = self._build_plan_extraction_prompt(message, timezone, channel)
        response = await self.gemini_service.client.aio.models.generate_content(
            model=self.settings.gemini_model,
            contents=prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0),
        )
        return self._parse_json_object(getattr(response, "text", ""))

    async def _extract_plan_json_with_modelscope(self, message: str, timezone: str, channel: str) -> dict[str, Any] | None:
        prompt = self._build_plan_extraction_prompt(message, timezone, channel)
        response = await self.modelscope_service.create_chat_completion(
            messages=[
                {"role": "system", "content": "你是提醒规划助手，只输出一个 JSON 对象，不要输出任何额外说明。"},
                {"role": "user", "content": prompt},
            ],
            tools=None,
        )
        content = ((response.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        return self._parse_json_object(content)

    def _build_json_extraction_prompt(self, message: str, timezone: str, channel: str) -> str:
        return (
            "请从下面这句中文提醒请求中提取结构化 JSON。\n"
            "只输出一个 JSON 对象，不要输出 markdown，不要输出解释。\n"
            f"用户时区: {timezone}\n"
            f"默认渠道: {channel or 'web'}\n"
            f"当前日期: {datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S %z')}\n"
            "要求:\n"
            "1. 如果用户是在创建提醒，intent 填 create_reminder。\n"
            "2. 对“明天下午3点”“今晚8点”“后天早上9点”“今天18点”这类表达，必须直接解析成 ISO 8601 时间字符串，绝对不要追问。\n"
            "3. 只有真的无法唯一判断时，need_follow_up 才为 true，例如仅说“周五提醒我”但没有几点。\n"
            "4. 如果已经包含日期词（今天/明天/后天）和具体小时（如3点、8点），need_follow_up 必须为 false。\n"
            "5. 如果能创建，need_follow_up 为 false，reply 可以为空字符串。\n"
            "6. 输出字段固定为: intent,title,content,remind_time,repeat_type,repeat_value,priority,channel_type,need_follow_up,reply。\n"
            '7. 示例输入: "明天下午3点提醒我交论文初稿"\n'
            '示例输出: {"intent":"create_reminder","title":"交论文初稿","content":null,"remind_time":"2026-03-28T15:00:00+08:00","repeat_type":"none","repeat_value":null,"priority":"medium","channel_type":"web","need_follow_up":false,"reply":""}\n'
            f"用户原话: {message}"
        )

    def _build_plan_extraction_prompt(self, message: str, timezone: str, channel: str) -> str:
        return (
            "请根据用户的中文需求，生成一个可执行的提醒计划 JSON。\n"
            "只输出一个 JSON 对象，不要输出 markdown，不要输出解释。\n"
            f"用户时区: {timezone}\n"
            f"默认渠道: {channel or 'web'}\n"
            f"当前日期: {datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S %z')}\n"
            "目标:\n"
            "1. 如果用户想让你安排作息、日程、健康生活提醒、学习节奏或习惯打卡，请生成 reminders 数组。\n"
            "2. 每条 reminder 必须包含 title 和 remind_time，时间要用 ISO 8601。\n"
            "3. 默认生成 3 到 6 条最有价值的提醒，避免过度密集。\n"
            "4. 如果用户目标不够明确，need_follow_up 才设为 true。\n"
            "5. 这不是医疗建议；仅根据用户要求生成一般性的生活提醒。\n"
            "输出字段固定为: intent,summary,reminders,need_follow_up,reply。\n"
            "其中 reminders 是数组，元素字段固定为: title,content,remind_time,repeat_type,repeat_value,priority,channel_type。\n"
            '示例输入: "帮我安排一个健康一点的明天，记得吃早餐、午饭后散步、晚上早点睡。"\n'
            '示例输出: {"intent":"plan_reminders","summary":"我按更规律的一天帮你安排了几个关键提醒。","reminders":[{"title":"吃早餐","content":"让早晨先稳定下来。","remind_time":"2026-03-28T08:00:00+08:00","repeat_type":"none","repeat_value":null,"priority":"medium","channel_type":"web"},{"title":"午饭后散步","content":"饭后活动 15 到 20 分钟。","remind_time":"2026-03-28T13:00:00+08:00","repeat_type":"none","repeat_value":null,"priority":"medium","channel_type":"web"},{"title":"准备睡觉","content":"提前放下手机，准备休息。","remind_time":"2026-03-28T22:30:00+08:00","repeat_type":"none","repeat_value":null,"priority":"medium","channel_type":"web"}],"need_follow_up":false,"reply":""}\n'
            f"用户原话: {message}"
        )

    def _parse_json_object(self, text: str) -> dict[str, Any] | None:
        raw = (text or "").strip()
        if not raw:
            return None
        if raw.startswith("```"):
            raw = raw.strip("`")
            raw = raw.replace("json", "", 1).strip()
        start = raw.find("{")
        end = raw.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        try:
            return json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            return None

    def _recover_create_json(self, extracted: dict[str, Any], message: str, timezone: str, channel: str) -> dict[str, Any]:
        recovered = dict(extracted)
        title = str(recovered.get("title") or "").strip()
        remind_time = str(recovered.get("remind_time") or "").strip()

        if not title:
            recovered_title = self._extract_title_from_message(message)
            if recovered_title:
                recovered["title"] = recovered_title

        if not remind_time:
            recovered_time = self._parse_natural_remind_time(message, timezone)
            if recovered_time:
                recovered["remind_time"] = recovered_time

        if recovered.get("intent") != "create_reminder" and (recovered.get("title") or recovered.get("remind_time")):
            recovered["intent"] = "create_reminder"

        recovered["channel_type"] = str(recovered.get("channel_type") or channel or "web").lower()
        recovered["priority"] = recovered.get("priority") or "medium"
        recovered["repeat_type"] = recovered.get("repeat_type") or "none"
        recovered["content"] = recovered.get("content") or None
        recovered["repeat_value"] = recovered.get("repeat_value") or None

        if recovered.get("title") and recovered.get("remind_time"):
            recovered["need_follow_up"] = False
            recovered["reply"] = ""

        return recovered

    def _extract_title_from_message(self, message: str) -> str:
        structured = self._extract_structured_title(message)
        if structured:
            return structured

        normalized = message.strip()
        patterns = [
            r"提醒我(.+)$",
            r"记得(.+)$",
            r"帮我记得(.+)$",
            r"帮我(.+)$",
            r"(?:设置|创建)?提醒[:：]?\s*(.+)$",
        ]
        for pattern in patterns:
            match = re.search(pattern, normalized)
            if not match:
                continue
            candidate = match.group(1).strip()
            candidate = re.sub(r"^(在|于)", "", candidate).strip()
            candidate = re.sub(r"(今天|明天|后天|今晚|今早|今晨|今下午|明早|明晨|上午|下午|中午|晚上)\s*\d{1,2}点(?:半|\d{1,2}分)?", "", candidate).strip()
            candidate = re.sub(r"^(提醒|发送|通知)", "", candidate).strip()
            candidate = re.sub(r"(提醒我|记得|发送提醒|提醒)$", "", candidate).strip()
            if candidate:
                return candidate

        temporal_prefixes = [
            r"^(今天|明天|后天|今晚|今早|今晨|明早|明晨)",
            r"^(上午|下午|中午|晚上)",
            r"^\d{1,2}点(?:半|\d{1,2}分)?",
        ]
        candidate = normalized
        for pattern in temporal_prefixes:
            candidate = re.sub(pattern, "", candidate).strip()
        candidate = re.sub(r"^(提醒我|记得|帮我|提醒)", "", candidate).strip()
        candidate = re.sub(r"(提醒我|记得|提醒)$", "", candidate).strip()
        return candidate[:100].strip() if candidate else ""

    def _parse_natural_remind_time(self, message: str, timezone: str) -> str | None:
        text = re.sub(r"\s+", "", message)
        tz = ZoneInfo(timezone or "Asia/Shanghai")
        now = datetime.now(tz)

        day_offset = 0
        if "大后天" in text:
            day_offset = 3
        elif "后天" in text:
            day_offset = 2
        elif "明天" in text:
            day_offset = 1
        elif any(token in text for token in ("今天", "今晚", "今早", "今晨", "今下午")):
            day_offset = 0

        period = None
        if "凌晨" in text:
            period = "凌晨"
        elif "早上" in text or "上午" in text or "今早" in text or "今晨" in text or "明早" in text or "明晨" in text:
            period = "上午"
        elif "中午" in text:
            period = "中午"
        elif "下午" in text:
            period = "下午"
        elif "晚上" in text or "今晚" in text:
            period = "晚上"

        match = re.search(r"(\d{1,2})点(?:(半)|(\d{1,2})分?)?", text)
        if not match:
            match = re.search(r"(\d{1,2})[:：](\d{1,2})", text)
            if not match:
                return None
            hour = int(match.group(1))
            minute = int(match.group(2))
        else:
            hour = int(match.group(1))
            if match.group(2):
                minute = 30
            else:
                minute = int(match.group(3) or 0)

        if period == "下午" and 1 <= hour <= 11:
            hour += 12
        elif period == "晚上" and 1 <= hour <= 11:
            hour += 12
        elif period == "中午":
            if hour == 12:
                hour = 12
            elif 1 <= hour <= 10:
                hour += 12
        elif period == "凌晨" and hour == 12:
            hour = 0

        target = (now + timedelta(days=day_offset)).replace(hour=hour, minute=minute, second=0, microsecond=0)
        if day_offset == 0 and target <= now and ("今天" in text or "今晚" in text or "今早" in text or "今晨" in text or "今下午" in text):
            target = target + timedelta(days=1)
        return target.isoformat()

    def _finalize_reply(self, model_reply: str | None, tool_name: str | None, tool_result: dict[str, Any] | None) -> str:
        explicit = self._build_tool_reply(tool_name, tool_result)
        if explicit:
            return explicit
        text = (model_reply or "").strip()
        return text or "我暂时没有拿到明确结果，请稍后再试，或者去 /docs 手动查看提醒。"

    def _build_tool_reply(self, tool_name: str | None, tool_result: dict[str, Any] | None) -> str | None:
        if not tool_name or not tool_result:
            return None
        if tool_name == "create_reminder":
            return f"已为你创建提醒：{self._format_display_time(tool_result.get('next_remind_time'))} {tool_result.get('title') or '未命名提醒'}。当前状态：{tool_result.get('status') or 'pending'}。"
        if tool_name == "list_reminders":
            count = int(tool_result.get("count") or 0)
            items = tool_result.get("items") or []
            if count == 0 or not items:
                return "你当前没有符合条件的提醒。"
            lines = [f"共找到 {count} 条提醒。"]
            for item in items[:5]:
                lines.append(f"#{item.get('id')} {item.get('title') or '未命名提醒'}，时间：{self._format_display_time(item.get('next_remind_time'))}，状态：{item.get('status') or 'unknown'}。")
            if count > 5:
                lines.append("其余提醒请到列表里继续查看。")
            return "\n".join(lines)
        if tool_name == "update_reminder":
            return f"已更新提醒 #{tool_result.get('reminder_id')}：{tool_result.get('title') or '这条提醒'}。新的提醒时间是 {self._format_display_time(tool_result.get('next_remind_time'))}，当前状态：{tool_result.get('status') or 'pending'}。"
        if tool_name == "delete_reminder":
            return f"已删除提醒 #{tool_result.get('reminder_id')}。"
        if tool_name == "snooze_reminder":
            return f"已将提醒 #{tool_result.get('reminder_id')} 延后，新的提醒时间是 {self._format_display_time(tool_result.get('next_remind_time'))}。"
        if tool_name == "mark_done":
            return f"已将提醒 #{tool_result.get('reminder_id')} 标记为完成。"
        return None

    def _format_display_time(self, value: Any) -> str:
        if not value:
            return "未设置时间"
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            return datetime.fromisoformat(text).strftime("%Y-%m-%d %H:%M")
        except ValueError:
            return text

    def _should_fallback_to_modelscope(self, exc: errors.ClientError) -> bool:
        status_code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
        message = str(exc)
        return bool(status_code == 429 or "RESOURCE_EXHAUSTED" in message or "quota" in message.lower())

    def _normalize_args(self, value: Any) -> dict[str, Any]:
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError as exc:
                raise HTTPException(status_code=400, detail=f"Tool arguments are not valid JSON: {exc}") from exc
        if not isinstance(value, dict):
            raise HTTPException(status_code=400, detail="Tool arguments must be a JSON object")
        return value

    def _try_pending_plan_action(self, payload: AgentChatRequest, user_id: int) -> dict[str, Any] | None:
        session_key = self._pending_plan_key(user_id, payload.session_id)
        pending_plan = self.pending_plan_store.get(session_key)
        if not pending_plan:
            return None

        compact = re.sub(r"\s+", "", payload.message or "")
        confirm_words = {
            "确认创建",
            "确认创建草案",
            "按草案创建",
            "创建这些",
            "创建草案",
            "就按这个创建",
        }
        cancel_words = {
            "取消草案",
            "取消创建",
            "先别创建",
            "不创建了",
            "算了",
        }

        if compact in confirm_words:
            created_items: list[dict[str, Any]] = []
            for spec in pending_plan.get("reminders", []):
                if not isinstance(spec, dict):
                    continue
                tool_payload = {
                    "title": spec.get("title"),
                    "content": spec.get("content"),
                    "source_text": pending_plan.get("source_text") or payload.message,
                    "remind_time": spec.get("remind_time"),
                    "repeat_type": spec.get("repeat_type") or "none",
                    "repeat_value": spec.get("repeat_value"),
                    "priority": spec.get("priority") or "medium",
                    "channel_type": spec.get("channel_type") or payload.channel,
                }
                if not tool_payload["title"] or not tool_payload["remind_time"]:
                    continue
                created_items.append(self._execute_tool("create_reminder", tool_payload, user_id, payload.channel))

            self.pending_plan_store.pop(session_key, None)
            if not created_items:
                return {
                    "intent": "plan_confirm",
                    "reply": "这份草案里没有可创建的提醒，所以我还没有写入系统。你可以换个说法让我重新整理。",
                    "tool_payload": pending_plan,
                    "tool_result": {"count": 0, "items": []},
                }

            lines = [f"已按草案为你创建 {len(created_items)} 条提醒："]
            for item in created_items[:5]:
                lines.append(f"- {self._format_display_time(item.get('next_remind_time'))} {item.get('title') or '未命名提醒'}")
            if len(created_items) > 5:
                lines.append("其余提醒也已经一并创建。")
            return {
                "intent": "plan_confirm",
                "reply": "\n".join(lines),
                "tool_payload": pending_plan,
                "tool_result": {"count": len(created_items), "items": created_items},
            }

        if compact in cancel_words:
            self.pending_plan_store.pop(session_key, None)
            return {
                "intent": "plan_cancel",
                "reply": "好的，这份提醒草案我先取消了，没有写入系统。你想重新调整时再告诉我。",
                "tool_payload": pending_plan,
                "tool_result": None,
            }

        return None

    async def _try_model_plan_create(self, payload: AgentChatRequest, timezone: str, user_id: int) -> dict[str, Any] | None:
        if not self._looks_like_plan_request(payload.message):
            return None

        extracted = None
        if self.gemini_service.is_configured:
            try:
                extracted = await self._extract_plan_json_with_gemini(payload.message, timezone, payload.channel)
            except errors.ClientError as exc:
                if not self._should_fallback_to_modelscope(exc):
                    return None
            except Exception:
                pass

        if extracted is None and self.modelscope_service.is_configured:
            try:
                extracted = await self._extract_plan_json_with_modelscope(payload.message, timezone, payload.channel)
            except Exception:
                return None

        if not extracted:
            return None

        if extracted.get("need_follow_up"):
            return {
                "intent": "plan_reminders",
                "reply": extracted.get("reply") or "我还需要补充一点信息，才能帮你整理提醒草案。",
                "tool_payload": extracted,
                "tool_result": None,
            }

        reminder_specs = extracted.get("reminders") or []
        if not isinstance(reminder_specs, list) or not reminder_specs:
            return None

        normalized_specs: list[dict[str, Any]] = []
        for spec in reminder_specs:
            if not isinstance(spec, dict):
                continue
            normalized = {
                "title": spec.get("title"),
                "content": spec.get("content"),
                "source_text": payload.message,
                "remind_time": spec.get("remind_time"),
                "repeat_type": spec.get("repeat_type") or "none",
                "repeat_value": spec.get("repeat_value"),
                "priority": spec.get("priority") or "medium",
                "channel_type": spec.get("channel_type") or payload.channel,
            }
            if not normalized["title"] or not normalized["remind_time"]:
                continue
            normalized_specs.append(normalized)

        if not normalized_specs:
            return None

        normalized_specs = self._expand_weekly_plan_specs(payload.message, normalized_specs, timezone)

        session_key = self._pending_plan_key(user_id, payload.session_id)
        self.pending_plan_store[session_key] = {
            "summary": extracted.get("summary"),
            "reply": extracted.get("reply"),
            "reminders": normalized_specs,
            "source_text": payload.message,
            "created_at": datetime.now().isoformat(),
        }

        summary = self._sanitize_plan_summary(str(extracted.get("summary") or ""))
        reply_lines = []
        if summary:
            reply_lines.append(f"{summary}（以下仅为草案，尚未创建）")
        else:
            reply_lines.append("我先为你整理了一份提醒草案，当前还没有真正创建。")
        reply_lines.append(f"下面是 {len(normalized_specs)} 条待确认的提醒：")
        reply_lines.extend(self._format_plan_draft_lines(normalized_specs))
        reply_lines.append("只有在你明确回复“确认创建”后，我才会真正创建这些提醒。回复“取消草案”即可放弃。")

        return {
            "intent": "plan_draft",
            "reply": "\n".join(reply_lines),
            "tool_payload": extracted,
            "tool_result": {"count": len(normalized_specs), "items": normalized_specs},
        }

    def _handle_gemini_client_error(self, exc: errors.ClientError) -> str:
        status_code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
        message = str(exc)
        if status_code == 429 or "RESOURCE_EXHAUSTED" in message or "quota" in message.lower():
            return "当前 Gemini 配额已用完，正在尝试备用模型。"
        if status_code == 400:
            return "当前请求没有被模型正确理解。你可以换一种更明确的说法，或者先去 /docs 手动创建提醒。"
        return "当前智能解析服务暂时不可用。你可以稍后再试，或者先去 /docs 手动创建提醒。"

    def _log(self, payload: AgentChatRequest, intent: str | None, tool_name: str | None, tool_payload: dict[str, Any] | None, reply: str) -> None:
        self.conversation_repo.create(
            user_id=payload.user_id,
            session_id=payload.session_id,
            channel=payload.channel,
            user_message=payload.message,
            agent_intent=intent,
            tool_name=tool_name,
            tool_payload=tool_payload,
            agent_response=reply,
        )
