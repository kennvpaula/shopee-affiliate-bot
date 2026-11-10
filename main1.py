"""
Ponto de entrada da automação.

Fluxo:
1. Busca ofertas na Shopee Affiliate API
2. Filtra as que ainda não foram enviadas (consulta Supabase)
3. Formata e dispara pro Telegram e WhatsApp
4. Marca como enviadas no Supabase

Execução local:
    python main.py

Execução agendada:
    Ver .github/workflows/scheduler.yml
"""
import sys

from clients.shopee_client import ShopeeClient
from clients.telegram_client import TelegramClient
from clients.whatsapp_client import WhatsAppClient
from core.formatter import format_telegram_message, format_whatsapp_body_params
from db.supabase_client import was_already_sent, mark_as_sent
from config.settings import settings


def _unwrap_error(exc: Exception) -> Exception:
    """Se for um RetryError do tenacity, revela a exceção real escondida dentro dele."""
    if type(exc).__name__ == "RetryError":
        try:
            return exc.last_attempt.exception()
        except Exception:
            pass
    return exc


def run(keyword: str = "", max_offers: int = 5) -> None:
    shopee = ShopeeClient()
    telegram = TelegramClient()
    whatsapp = WhatsAppClient()

    print(f"[INFO] Buscando ofertas na Shopee (keyword='{keyword}')...")
    offers = shopee.get_offers(keyword=keyword, limit=max_offers)

    if not offers:
        print("[INFO] Nenhuma oferta retornada pela API.")
        return

    novas_enviadas = 0

    for offer in offers:
        item_id = str(offer.get("itemId"))

        if was_already_sent(item_id):
            print(f"[SKIP] Oferta {item_id} já foi enviada antes.")
            continue

        product_name = offer.get("productName", "Produto")

        try:
            # --- Telegram ---
            telegram_text = format_telegram_message(offer)
            telegram.send_message(telegram_text)
            print(f"[OK] Enviado ao Telegram: {product_name}")

            # --- WhatsApp (template) ---
            if settings.WHATSAPP_TEMPLATE_NAME and settings.WHATSAPP_TO_NUMBERS:
                body_params = format_whatsapp_body_params(offer)
                header_image_url = offer.get("imageUrl")
                whatsapp.broadcast_template(
                    template_name=settings.WHATSAPP_TEMPLATE_NAME,
                    body_params=body_params,
                    to_numbers=settings.WHATSAPP_TO_NUMBERS,
                    header_image_url=header_image_url,
                )
                print(f"[OK] Enviado ao WhatsApp: {product_name}")

            mark_as_sent(item_id, product_name)
            novas_enviadas += 1

        except Exception as exc:
            # Não interrompe o loop por causa de uma oferta problemática
            real_exc = _unwrap_error(exc)
            print(f"[ERRO] Falha ao processar oferta {item_id} ({product_name}): {real_exc}")

    print(f"[FIM] {novas_enviadas} oferta(s) nova(s) enviada(s) de {len(offers)} recebida(s).")


if __name__ == "__main__":
    keyword_arg = sys.argv[1] if len(sys.argv) > 1 else ""
    run(keyword=keyword_arg)
