"""
Cliente do Telegram Bot API (chamadas REST diretas).

Os textos são enviados SEM parse_mode de propósito: assim os símbolos do WhatsApp
(*negrito*, ~tachado~) chegam literais e, quando você copia e cola o post no
WhatsApp, a formatação aparece certa lá.

Docs: https://core.telegram.org/bots/api#sendphoto
"""
import time

import httpx

from config.settings import settings

CAPTION_LIMIT = 1024  # limite do Telegram para legenda de foto


class TelegramClient:
    def __init__(self):
        self.token = settings.TELEGRAM_BOT_TOKEN
        self.chat_id = settings.TELEGRAM_CHAT_ID
        self.base_url = f"https://api.telegram.org/bot{self.token}"

    def _post(self, method: str, payload: dict, attempts: int = 3) -> dict:
        for _ in range(attempts):
            with httpx.Client(timeout=30) as client:
                response = client.post(f"{self.base_url}/{method}", json=payload)

            if response.status_code == 429:  # muitos envios seguidos: espera o que o Telegram pedir
                try:
                    wait = int(response.json().get("parameters", {}).get("retry_after", 5))
                except Exception:
                    wait = 5
                print(f"[AVISO] Telegram pediu pausa de {wait}s (limite de envios)...")
                time.sleep(wait + 1)
                continue

            if response.status_code >= 400:
                raise RuntimeError(f"Erro Telegram API [{response.status_code}]: {response.text}")
            return response.json()

        raise RuntimeError("Telegram: limite de envios excedido após várias tentativas")

    def send_message(self, text: str, silent: bool = True, chat_id: str | None = None) -> dict:
        payload = {
            "chat_id": chat_id or self.chat_id,
            "text": text,
            "disable_web_page_preview": True,
            "disable_notification": silent,
        }
        return self._post("sendMessage", payload)

    def send_photo(
        self, photo_url: str, caption: str = "", silent: bool = True, chat_id: str | None = None
    ) -> dict:
        payload = {
            "chat_id": chat_id or self.chat_id,
            "photo": photo_url,
            "caption": caption,
            "disable_notification": silent,
        }
        return self._post("sendPhoto", payload)

    def send_post(self, photo_url: str | None, caption: str, silent: bool = True) -> str:
        """
        Envia o post com a foto em cima e o texto embaixo (legenda).
        Se a foto for recusada (link quebrado, imagem inválida) ou a legenda passar
        do limite, envia só o texto. Retorna "foto" ou "texto" (pro log).
        """
        if photo_url and len(caption) <= CAPTION_LIMIT:
            try:
                self.send_photo(photo_url, caption, silent)
                return "foto"
            except RuntimeError as exc:
                print(f"[AVISO] Foto recusada pelo Telegram ({str(exc)[:110]}); enviando só texto.")

        self.send_message(caption, silent)
        return "texto"
