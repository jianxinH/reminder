import re
from datetime import datetime

from sqlalchemy.orm import Session

from app.services.reminder_service import ReminderService


class WeComCommandService:
    def __init__(self, db: Session):
        self.db = db
        self.reminder_service = ReminderService(db)

    def try_handle(self, user_id: int, content: str) -> str | None:
        text = (content or "").strip()
        if not text:
            return "我没有收到内容。你可以发送“帮助”查看可用命令。"

        normalized = text.lower()
        if normalized in {"帮助", "help", "菜单"}:
            return self._help_text()

        if normalized in {"查看提醒", "我的提醒", "list", "ls"}:
            return self._list_reminders(user_id)

        done_match = re.fullmatch(r"(?:完成|done)\s+(\d+)", text, flags=re.IGNORECASE)
        if done_match:
            reminder_id = int(done_match.group(1))
            reminder = self.reminder_service.get_reminder(reminder_id)
            if reminder.user_id != user_id:
                return "这条提醒不属于你，不能直接操作。"
            self.reminder_service.mark_done(reminder_id)
            return f"已完成提醒 #{reminder_id}：{reminder.title}"

        snooze_match = re.fullmatch(r"(?:延后|snooze)\s+(\d+)\s+(\d+)", text, flags=re.IGNORECASE)
        if snooze_match:
            reminder_id = int(snooze_match.group(1))
            minutes = int(snooze_match.group(2))
            reminder = self.reminder_service.get_reminder(reminder_id)
            if reminder.user_id != user_id:
                return "这条提醒不属于你，不能直接操作。"
            self.reminder_service.snooze_reminder(reminder_id, minutes)
            return f"已将提醒 #{reminder_id} 延后 {minutes} 分钟。"

        delete_match = re.fullmatch(r"(?:删除|delete)\s+(\d+)", text, flags=re.IGNORECASE)
        if delete_match:
            reminder_id = int(delete_match.group(1))
            reminder = self.reminder_service.get_reminder(reminder_id)
            if reminder.user_id != user_id:
                return "这条提醒不属于你，不能直接操作。"
            self.reminder_service.delete_reminder(reminder_id)
            return f"已删除提醒 #{reminder_id}：{reminder.title}"

        return None

    def _list_reminders(self, user_id: int) -> str:
        reminders = self.reminder_service.list_recent_reminders(user_id=user_id, limit=5, include_finished=False)
        if not reminders:
            return "你目前没有待处理提醒。"

        lines = ["最近 5 条待处理提醒："]
        for item in reminders:
            when = item.next_remind_time
            if isinstance(when, datetime):
                when_text = when.strftime("%m-%d %H:%M")
            else:
                when_text = str(when)
            lines.append(f"#{item.id} {item.title} @ {when_text}")
        lines.append("可用命令：完成 123 / 延后 123 10 / 删除 123")
        return "\n".join(lines)

    def _help_text(self) -> str:
        return (
            "可用命令：\n"
            "1. 查看提醒\n"
            "2. 完成 123\n"
            "3. 延后 123 10\n"
            "4. 删除 123\n"
            "5. 直接发送自然语言，例如：明天下午三点提醒我开会"
        )
