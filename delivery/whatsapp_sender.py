import requests
import logging
from urllib.parse import quote

logger = logging.getLogger(__name__)


class WhatsAppSender:
    def __init__(self, api_key: str):
        self._api_key = api_key

    def send(self, phone_numbers: list[str], text: str) -> bool:
        encoded = quote(text)
        any_success = False
        for phone in phone_numbers:
            try:
                url = f"https://api.callmebot.com/whatsapp.php?phone={phone}&text={encoded}&apikey={self._api_key}"
                resp = requests.get(url, timeout=15)
                if "Message queued" in resp.text:
                    logger.info("WhatsApp sent to %s", phone)
                    any_success = True
                else:
                    logger.warning("WhatsApp send unexpected response for %s: %s", phone, resp.text[:200])
            except Exception as exc:
                logger.error("WhatsApp send failed for %s: %s", phone, exc)
        return any_success
