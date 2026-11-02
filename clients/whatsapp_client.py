"""
Cliente do WhatsApp Cloud API oficial (Meta for Developers).

Dois modos de envio:
1. Template message: obrigatório se o destinatário não te escreveu nas últimas 24h.
   O template precisa estar previamente criado e APROVADO no Meta Business Manager.
2. Free-form text message: só funciona dentro da janela de 24h de uma conversa iniciada
   pelo usuário. Para disparos em massa/automáticos, use template.

Docs oficiais: https://developers.facebook.com/docs/whatsapp/cloud-api
"""
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from config.settings import settings


class WhatsAppClient:
    def __init__(self):
        self.token = settings.WHATSAPP_TOKEN
        self.phone_number_id = settings.WHATSAPP_PHONE_NUMBER_ID
        self.api_version = settings.WHATSAPP_API_VERSION
        self.base_url = (
            f"https://graph.facebook.com/{self.api_version}/{self.phone_number_id}/messages"
        )

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2))
    def _post(self, payload: dict) -> dict:
        with httpx.Client(timeout=30) as client:
            response = client.post(self.base_url, headers=self._headers(), json=payload)
            if response.status_code >= 400:
                # Loga o corpo do erro pra facilitar debug (rate limit, template inválido etc)
                raise RuntimeError(f"Erro WhatsApp API [{response.status_code}]: {response.text}")
            return response.json()

    def send_template(
        self,
        to_number: str,
        template_name: str,
        language_code: str = "pt_BR",
        body_params: dict[str, str] | None = None,
        header_image_url: str | None = None,
    ) -> dict:
        """
        Envia mensagem usando um template aprovado.

        body_params agora é um dicionário {nome_da_variavel: valor}, pois a Meta
        passou a exigir variáveis NOMEADAS no template (ex: {{product_name}})
        em vez do formato antigo posicional ({{1}}, {{2}}...).

        Exemplo:
            body_params={
                "product_name": "Gel de Limpeza Facial Darrow",
                "original_price": "96,99",
                "discount_price": "57,54",
                "coupon_code": "DARROW15",
                "product_link": "https://...",
            }

        header_image_url, se o template tiver um cabeçalho do tipo Imagem, define
        qual foto será exibida (precisa ser uma URL pública e acessível, tipo
        a imagem do produto retornada pela Shopee).
        """
        components = []

        if header_image_url:
            components.append(
                {
                    "type": "header",
                    "parameters": [
                        {"type": "image", "image": {"link": header_image_url}}
                    ],
                }
            )

        if body_params:
            components.append(
                {
                    "type": "body",
                    "parameters": [
                        {"type": "text", "parameter_name": name, "text": value}
                        for name, value in body_params.items()
                    ],
                }
            )

        payload = {
            "messaging_product": "whatsapp",
            "to": to_number,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": language_code},
                "components": components,
            },
        }
        return self._post(payload)

    def send_text(self, to_number: str, text: str) -> dict:
        """Só funciona dentro da janela de 24h de conversa ativa. Use send_template fora dela."""
        payload = {
            "messaging_product": "whatsapp",
            "to": to_number,
            "type": "text",
            "text": {"body": text, "preview_url": True},
        }
        return self._post(payload)

    def broadcast_template(
        self,
        template_name: str,
        body_params: dict[str, str],
        to_numbers: list[str],
        header_image_url: str | None = None,
        language_code: str = "pt_BR",
    ) -> list[dict]:
        """Envia o mesmo template pra uma lista de números."""
        results = []
        for number in to_numbers:
            result = self.send_template(
                number,
                template_name,
                body_params=body_params,
                header_image_url=header_image_url,
                language_code=language_code,
            )
            results.append(result)
        return results
