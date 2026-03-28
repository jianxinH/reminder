import base64
import hashlib
import os
import struct
import xml.etree.ElementTree as ET

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from app.core.config import get_settings


class WeComCallbackService:
    def __init__(self):
        self.settings = get_settings()

    @property
    def is_configured(self) -> bool:
        return bool(
            self.settings.wecom_token
            and self.settings.wecom_aes_key
            and self.settings.wecom_corp_id
        )

    def verify_signature(self, msg_signature: str, timestamp: str, nonce: str, encrypted: str) -> bool:
        if not self.is_configured:
            return False
        expected = self._sha1(self.settings.wecom_token, timestamp, nonce, encrypted)
        return expected == msg_signature

    def verify_url(self, msg_signature: str, timestamp: str, nonce: str, echostr: str) -> str:
        if not self.verify_signature(msg_signature, timestamp, nonce, echostr):
            raise ValueError("Invalid WeCom signature")
        return self._decrypt(echostr)

    def decrypt_post_body(self, body: bytes, msg_signature: str, timestamp: str, nonce: str) -> str:
        root = ET.fromstring(body.decode("utf-8"))
        encrypted = root.findtext("Encrypt", default="")
        if not encrypted:
            raise ValueError("Missing Encrypt field")
        if not self.verify_signature(msg_signature, timestamp, nonce, encrypted):
            raise ValueError("Invalid WeCom signature")
        return self._decrypt(encrypted)

    def _decrypt(self, encrypted_text: str) -> str:
        aes_key = base64.b64decode(self.settings.wecom_aes_key + "=")
        iv = aes_key[:16]
        cipher = Cipher(algorithms.AES(aes_key), modes.CBC(iv), backend=default_backend())
        decryptor = cipher.decryptor()
        padded = decryptor.update(base64.b64decode(encrypted_text)) + decryptor.finalize()
        plain = self._pkcs7_unpad(padded)

        msg_len = struct.unpack("!I", plain[16:20])[0]
        msg = plain[20 : 20 + msg_len]
        receive_id = plain[20 + msg_len :].decode("utf-8")
        if receive_id != self.settings.wecom_corp_id:
            raise ValueError("Invalid WeCom corp id")
        return msg.decode("utf-8")

    def _pkcs7_unpad(self, text: bytes) -> bytes:
        pad = text[-1]
        if pad < 1 or pad > 32:
            return text
        return text[:-pad]

    def _sha1(self, token: str, timestamp: str, nonce: str, encrypted: str) -> str:
        raw = "".join(sorted([token, timestamp, nonce, encrypted]))
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()
