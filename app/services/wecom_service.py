import httpx

from app.core.config import get_settings


class WeComService:
    def __init__(self):
        self.settings = get_settings()

    @property
    def is_configured(self) -> bool:
        return bool(
            self.settings.wecom_corp_id
            and self.settings.wecom_agent_id
            and self.settings.wecom_secret
        )

    async def _get_access_token(self) -> dict:
        if not self.is_configured:
            return {"ok": False, "description": "WeCom app credentials are not configured"}

        url = f"{self.settings.wecom_base_url}/cgi-bin/gettoken"
        params = {
            "corpid": self.settings.wecom_corp_id,
            "corpsecret": self.settings.wecom_secret,
        }
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            data = response.json()

        if data.get("errcode") != 0:
            return {"ok": False, "description": data.get("errmsg", "Failed to get WeCom access token"), "raw": data}
        return {"ok": True, "access_token": data.get("access_token"), "raw": data}

    async def send_message(self, touser: str, text: str) -> dict:
        token_result = await self._get_access_token()
        if not token_result.get("ok"):
            return token_result

        url = f"{self.settings.wecom_base_url}/cgi-bin/message/send"
        params = {"access_token": token_result["access_token"]}
        payload = {
            "touser": touser,
            "msgtype": "text",
            "agentid": int(self.settings.wecom_agent_id),
            "text": {"content": text},
            "safe": 0,
            "enable_duplicate_check": 0,
        }

        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(url, params=params, json=payload)
            response.raise_for_status()
            data = response.json()

        if data.get("errcode") != 0:
            return {"ok": False, "description": data.get("errmsg", "Unknown WeCom error"), "raw": data}
        return {"ok": True, "raw": data}
