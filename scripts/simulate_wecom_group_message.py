import argparse
import asyncio
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.api.routes.bot import _extract_wecom_actor_id, _extract_wecom_display_name, _normalize_wecom_content
from app.core.database import SessionLocal
from app.schemas.agent import AgentChatRequest
from app.services.agent_service import AgentService
from app.services.user_service import UserService
from app.services.wecom_command_service import WeComCommandService


def build_message(args: argparse.Namespace, content: str) -> dict[str, str]:
    message = {
        "MsgType": "text",
        "FromUserName": args.from_user,
        "Content": content,
        "CreateTime": args.create_time,
        "MsgId": args.msg_id,
    }
    if args.sender_userid:
        message["Sender_UserID"] = args.sender_userid
    if args.sender_name:
        message["Sender_Name"] = args.sender_name
    if args.userid:
        message["UserID"] = args.userid
    if args.username:
        message["UserName"] = args.username
    if args.external_userid:
        message["ExternalUserID"] = args.external_userid
    return message


async def run_single_turn(content: str, actor_id: str, display_name: str, session_id: str) -> None:
    db = SessionLocal()
    try:
        user = UserService(db).get_or_create_by_wecom_userid(actor_id, display_name=display_name)
        print("MATCHED USER")
        print(
            json.dumps(
                {
                    "id": user.id,
                    "username": user.username,
                    "display_name": user.display_name,
                    "wecom_userid": user.wecom_userid,
                    "default_channel": user.default_channel,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        print()

        normalized_content = _normalize_wecom_content(content)
        print("NORMALIZED CONTENT")
        print(normalized_content)
        print()

        command_reply = WeComCommandService(db).try_handle(user.id, normalized_content)
        if command_reply is not None:
            print("ROUTE")
            print("wecom_command")
            print()
            print("REPLY")
            print(command_reply)
            return

        result = await AgentService(db).chat(
            AgentChatRequest(
                user_id=user.id,
                channel="wecom",
                session_id=session_id,
                message=normalized_content,
            )
        )
        print("ROUTE")
        print("agent")
        print()
        print("RESULT")
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        db.close()


async def main() -> None:
    parser = argparse.ArgumentParser(description="Simulate a WeCom group @reminder message without sending an actual WeCom reply.")
    parser.add_argument("--content", default="@reminder 提醒我明天上午面试", help="Simulated group message content.")
    parser.add_argument("--from-user", default="reminder", help="Raw FromUserName from WeCom callback.")
    parser.add_argument("--sender-userid", default="", help="Preferred real speaker field from group callback.")
    parser.add_argument("--sender-name", default="", help="Preferred speaker display name from group callback.")
    parser.add_argument("--userid", default="", help="Fallback UserID field from callback.")
    parser.add_argument("--username", default="", help="Fallback UserName/display field from callback.")
    parser.add_argument("--external-userid", default="", help="Fallback ExternalUserID field from callback.")
    parser.add_argument("--create-time", default="1775000000", help="Fake CreateTime used for message identity.")
    parser.add_argument("--msg-id", default="debug-wecom-msg-001", help="Fake MsgId used for message identity.")
    parser.add_argument("--session-id", default="", help="Fixed conversation session id. Defaults to wecom_<actor_id>.")
    parser.add_argument("--interactive", action="store_true", help="Start an interactive multi-turn conversation loop.")
    args = parser.parse_args()

    message = build_message(args, args.content)
    actor_id = _extract_wecom_actor_id(message)
    display_name = _extract_wecom_display_name(message, actor_id)

    print("MESSAGE")
    print(json.dumps(message, ensure_ascii=False, indent=2))
    print()
    print("RESOLVED ACTOR")
    print(json.dumps({"actor_id": actor_id, "display_name": display_name}, ensure_ascii=False, indent=2))
    print()

    if not actor_id:
        print("ERROR: no actor id could be resolved from the simulated callback payload.")
        return

    session_id = args.session_id or f"wecom_{actor_id}"

    if args.interactive:
        print("INTERACTIVE MODE")
        print(f"session_id={session_id}")
        print("输入消息后回车即可；输入 exit 或 quit 结束。")
        print()
        while True:
            try:
                line = input("YOU> ").strip()
            except EOFError:
                break
            if not line:
                continue
            if line.lower() in {"exit", "quit"}:
                break
            print()
            await run_single_turn(line, actor_id, display_name, session_id)
            print()
        return

    await run_single_turn(args.content, actor_id, display_name, session_id)


if __name__ == "__main__":
    asyncio.run(main())
