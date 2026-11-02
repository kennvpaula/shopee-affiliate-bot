"""
Ponto de entrada. Cada rodagem:
  1. Busca ofertas na Shopee: 4 marcas (Boticário, Natura, Wepink, Eudora)
     + 3 listas gerais (top desconto, top vendas, top comissão)
  2. Aplica os filtros de qualidade (core/selector.py) e escolhe até 5 por marca
     e 3 por lista geral, sem repetir o que foi enviado nos últimos dias
  3. Posta cada oferta no Telegram (foto em cima + texto no modelo do WhatsApp)
  4. Registra no Supabase

Uso:
    python main.py                        rodagem completa
    python main.py --dry-run              só MOSTRA os posts (não envia, não grava)
    python main.py --only natura,vendas   só alguns blocos (bom pra testar)

Blocos: boticario, natura, wepink, eudora, desconto, vendas, comissao
"""
import argparse
import sys
import time

from clients.shopee_client import ShopeeClient
from clients.telegram_client import TelegramClient
from config.settings import settings
from core import selector
from core.formatter import format_post_caption, format_whatsapp_body_params
from db.supabase_client import get_recent_item_ids, mark_as_sent

PAGE_SIZE = 20
FETCH_DELAY = 0.4  # pausa entre consultas à Shopee (evita estourar o limite deles)
STATE = {"fetch_errors": 0}


def unwrap_error(exc: Exception) -> Exception:
    """Se for um RetryError do tenacity, revela a exceção real escondida dentro dele."""
    if type(exc).__name__ == "RetryError":
        try:
            return exc.last_attempt.exception()
        except Exception:
            pass
    return exc


# ------------------------------------------------------------ busca
def fetch_pool(shopee, *, keyword="", shop_id=None, sort_type=None, pages=2) -> list[dict]:
    items: list[dict] = []
    for page in range(1, pages + 1):
        try:
            nodes = shopee.get_offers(
                keyword=keyword, limit=PAGE_SIZE, page=page,
                sort_type=sort_type, shop_id=shop_id,
            )
        except Exception as exc:
            STATE["fetch_errors"] += 1
            print(
                f"[AVISO] Falha na busca (keyword='{keyword}', loja={shop_id}, "
                f"página {page}): {unwrap_error(exc)}"
            )
            break
        items.extend(nodes)
        if len(nodes) < PAGE_SIZE:
            break
        time.sleep(FETCH_DELAY)
    time.sleep(FETCH_DELAY)
    return items


def collect_brand_pool(shopee, key: str) -> list[dict]:
    cfg = selector.BRANDS[key]
    pool: dict = {}
    for keyword in cfg["keywords"]:
        for item in fetch_pool(shopee, keyword=keyword, sort_type=ShopeeClient.SORT_RELEVANCE):
            pool.setdefault(item["itemId"], item)
    for shop_id in cfg["shop_ids"]:
        for item in fetch_pool(shopee, shop_id=shop_id, sort_type=ShopeeClient.SORT_ITEM_SOLD_DESC):
            item["_from_brand_shop"] = True  # produtos da loja da marca dispensam o nome citar a marca
            pool[item["itemId"]] = item
    return list(pool.values())


def collect_general_pools(shopee) -> dict[str, list[dict]]:
    sold = fetch_pool(shopee, sort_type=ShopeeClient.SORT_ITEM_SOLD_DESC, pages=3)
    commission = fetch_pool(shopee, sort_type=ShopeeClient.SORT_COMMISSION_DESC, pages=3)
    union = {item["itemId"]: item for item in sold + commission}
    return {"desconto": list(union.values()), "vendas": sold, "comissao": commission}


# ------------------------------------------------------------ plano
def build_plan(shopee, only: set[str] | None, blocked_ids: set[str]):
    used: set[str] = set()
    plan = []
    general_pools = None

    for key, label in selector.BLOCKS:
        if only and key not in only:
            continue

        if key in selector.BRANDS:
            pool = collect_brand_pool(shopee, key)
            picked, passed = selector.pick_brand(pool, key, blocked_ids, used)
            wanted = selector.BRAND_COUNT
        else:
            if general_pools is None:
                general_pools = collect_general_pools(shopee)
            pool = general_pools[key]
            picked, passed = selector.pick_general(pool, key, blocked_ids, used)
            wanted = selector.GENERAL_COUNT

        print(f"[BLOCO {label}] buscados={len(pool)} passaram_nos_filtros={passed} escolhidos={len(picked)}")
        if len(picked) < wanted:
            print(f"[AVISO] {label}: só {len(picked)} de {wanted} (poucas ofertas boas e novas agora).")
        plan.append((key, label, picked))
    return plan


# ------------------------------------------------------------ envio
def build_whatsapp():
    """WhatsApp Cloud API: só se estiver LIGADO (WHATSAPP_ENABLED=true) e configurado."""
    if not settings.WHATSAPP_ENABLED:
        return None
    needed = [
        settings.WHATSAPP_TOKEN, settings.WHATSAPP_PHONE_NUMBER_ID,
        settings.WHATSAPP_TEMPLATE_NAME, settings.WHATSAPP_TO_NUMBERS,
    ]
    if not all(needed):
        print("[AVISO] WHATSAPP_ENABLED=true, mas faltam variáveis do WhatsApp. Pulando o WhatsApp.")
        return None
    from clients.whatsapp_client import WhatsAppClient
    return WhatsAppClient()


def send_plan(plan, dry_run: bool) -> int:
    telegram = None if dry_run else TelegramClient()
    whatsapp = None if dry_run else build_whatsapp()
    sent = 0

    for key, label, offers in plan:
        for offer in offers:
            name = offer.get("productName", "Produto")
            discount = offer.get("priceDiscountRate")
            tag = f" ({discount}% OFF)" if discount else ""
            caption = format_post_caption(
                offer, settings.WHATSAPP_GROUP_LINK, settings.TELEGRAM_GROUP_LINK
            )

            if dry_run:
                print(f"\n----- [{label}] {discount or 0}% OFF | loja: {offer.get('shopName')} -----")
                print(caption)
                continue

            try:
                how = telegram.send_post(offer.get("imageUrl"), caption, silent=settings.TELEGRAM_SILENT)
            except Exception as exc:
                print(f"[ERRO] [{label}] Telegram falhou para '{name[:60]}': {exc}")
                continue  # não registra: tenta de novo na próxima rodagem

            print(f"[OK] [{label}] enviado ({how}): {name[:70]}{tag}")
            try:
                mark_as_sent(str(offer["itemId"]), name, label)
            except Exception as exc:
                print(f"[AVISO] Não consegui registrar no Supabase (pode repetir depois): {exc}")

            if whatsapp:
                try:
                    whatsapp.broadcast_template(
                        template_name=settings.WHATSAPP_TEMPLATE_NAME,
                        body_params=format_whatsapp_body_params(offer),
                        to_numbers=settings.WHATSAPP_TO_NUMBERS,
                        header_image_url=offer.get("imageUrl"),
                        language_code=settings.WHATSAPP_TEMPLATE_LANGUAGE,
                    )
                except Exception as exc:
                    print(f"[AVISO] WhatsApp falhou: {unwrap_error(exc)}")

            sent += 1
            time.sleep(settings.SEND_DELAY_SECONDS)
    return sent


# ------------------------------------------------------------ principal
def run(only: set[str] | None = None, dry_run: bool = False) -> int:
    shopee = ShopeeClient()

    try:
        blocked_ids = get_recent_item_ids(settings.COOLDOWN_DAYS)
    except Exception as exc:
        message = f"Não consegui ler o Supabase (projeto pausado? credenciais?): {unwrap_error(exc)}"
        if not dry_run:
            print(f"[ERRO] {message}")
            return 1
        print(f"[AVISO] {message}\n[AVISO] Seguindo sem checar repetidas (é só simulação).")
        blocked_ids = set()

    print(f"[INFO] {len(blocked_ids)} oferta(s) enviada(s) nos últimos {settings.COOLDOWN_DAYS} dia(s) (não repetem).")
    plan = build_plan(shopee, only, blocked_ids)
    total = sum(len(offers) for _, _, offers in plan)
    print(f"[INFO] {total} oferta(s) escolhida(s) nesta rodagem.")

    sent = send_plan(plan, dry_run)
    if dry_run:
        print("\n[FIM] Simulação: nada foi enviado nem gravado.")
        return 0

    print(f"[FIM] {sent} de {total} oferta(s) postada(s) no Telegram.")
    if total == 0 and STATE["fetch_errors"]:
        return 1  # a Shopee falhou e nada foi escolhido: o GitHub deve marcar a rodagem como falha
    if total > 0 and sent == 0:
        return 1  # nenhum envio funcionou
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Bot de ofertas Shopee -> Telegram")
    parser.add_argument("--dry-run", action="store_true", help="só mostra os posts, não envia nem grava")
    parser.add_argument("--only", default="", help="blocos separados por vírgula (ex: natura,vendas)")
    args = parser.parse_args(argv)

    valid = {key for key, _ in selector.BLOCKS}
    only = {part.strip().lower() for part in args.only.split(",") if part.strip()}
    unknown = only - valid
    if unknown:
        print(f"Bloco(s) desconhecido(s): {', '.join(sorted(unknown))}. Opções: {', '.join(sorted(valid))}")
        return 2

    return run(only or None, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
