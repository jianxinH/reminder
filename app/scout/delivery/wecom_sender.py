from __future__ import annotations

import re
from pathlib import Path

import httpx


def send_report_to_wecom(
    report_path: str,
    corp_id: str = "",
    agent_id: str = "",
    secret: str = "",
    touser: str = "",
    base_url: str = "https://qyapi.weixin.qq.com",
    report_url: str = "",
    webhook_url: str = "",
) -> dict:
    content = build_wecom_message(report_path=report_path, report_url=report_url)

    if webhook_url.strip():
        return send_report_via_webhook(webhook_url=webhook_url.strip(), content=content)

    if not corp_id or not agent_id or not secret or not touser:
        raise RuntimeError("WeCom send failed: missing webhook or app credentials")

    access_token = get_access_token(corp_id=corp_id, secret=secret, base_url=base_url)
    response = httpx.post(
        f"{base_url}/cgi-bin/message/send",
        params={"access_token": access_token},
        json={
            "touser": touser.strip(),
            "msgtype": "text",
            "agentid": int(agent_id),
            "text": {"content": content},
            "safe": 0,
            "enable_duplicate_check": 0,
        },
        timeout=20.0,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("errcode") != 0:
        raise RuntimeError(f"WeCom send failed: {payload}")
    return payload


def send_report_via_webhook(webhook_url: str, content: str) -> dict:
    response = httpx.post(
        webhook_url,
        json={
            "msgtype": "text",
            "text": {"content": content},
        },
        timeout=20.0,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("errcode") != 0:
        raise RuntimeError(f"WeCom webhook send failed: {payload}")
    return payload


def get_access_token(corp_id: str, secret: str, base_url: str) -> str:
    response = httpx.get(
        f"{base_url}/cgi-bin/gettoken",
        params={"corpid": corp_id, "corpsecret": secret},
        timeout=20.0,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("errcode") != 0:
        raise RuntimeError(f"WeCom token failed: {payload}")
    return payload["access_token"]


def build_wecom_message(report_path: str, report_url: str = "") -> str:
    path = Path(report_path)
    content = path.read_text(encoding="utf-8")
    lines = [line.strip() for line in content.splitlines() if line.strip()]

    title = "AI Daily Scout 日报"
    item_lines: list[str] = []
    summary_lines: list[str] = []

    for line in lines:
        if line.startswith("# "):
            title = line[2:].strip()
        elif line.startswith("### "):
            item_lines.append(strip_heading_number(line[4:].strip()))
        elif line.startswith("- 摘要：") and len(summary_lines) < 5:
            summary_lines.append(line.replace("- 摘要：", "", 1).strip())

    message_parts = [title]
    if item_lines:
        message_parts.append("重点条目：")
        for index, item in enumerate(item_lines[:8], start=1):
            message_parts.append(f"{index}. {item}")
    if summary_lines:
        message_parts.append("摘要：")
        message_parts.extend(summary_lines[:5])
    if report_url:
        message_parts.append(f"完整日报：{report_url}")

    return "\n".join(message_parts)[:4000]


def strip_heading_number(value: str) -> str:
    return re.sub(r"^\d+\.\s*", "", value).strip()
