from datetime import datetime, timedelta


def compute_next_remind_time(current: datetime, repeat_type: str, repeat_value: str | None = None) -> datetime | None:
    if repeat_type == "none":
        return None
    if repeat_type == "daily":
        return current + timedelta(days=1)
    if repeat_type == "weekly":
        return current + timedelta(weeks=1)
    if repeat_type == "monthly":
        return current + timedelta(days=30)
    return None
