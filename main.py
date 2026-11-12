"""
Ponto de entrada. Cada rodagem:
  1. Busca ofertas: Shopee (top desconto/vendas/comissão + casa) e, quando
     pedido, Rakuten (Netshoes, Zattini e lojas de time; os cupons da Rakuten
     vão junto dos produtos em que se aplicam)
  2. Aplica os filtros de qualidade e escolhe as ofertas de cada bloco, sem
     repetir o que foi enviado nos últimos dias
  3. Posta cada oferta no Telegram (foto em cima + texto no modelo do WhatsApp)
  4. Registra no Supabase

Uso:
    python main.py                        Shopee (rodagem comum)
    python main.py --rakuten              Shopee + Rakuten
    python main.py --dry-run              só MOSTRA os posts (não envia, não grava)
    python main.py --only casa,vendas    só alguns blocos (bom pra testar)

Blocos da Shopee:  desconto, vendas, comissao, casa  (as 4 marcas de beleza estão desligadas: ACTIVE_BRANDS em core/selector.py)
Blocos da Rakuten: netshoes, zattini, times
Pedir um bloco da Rakuten em --only já liga a Rakuten.
"""
import argparse
import sys
import time
from datetime import datetime, timezone

from clients.shopee_client import ShopeeClient
from clients.telegram_client import TelegramClient
from config.settings import settings
from core import rakuten_rules as rk
from core import selector
from core.formatter import format_post_caption, format_whatsapp_body_params
from db.supabase_client import get_recent_item_ids, mark_as_sent

PAGE_SIZE = 20
BRAND_PAGES = 3    # páginas por busca de marca (Shopee)
GENERAL_PAGES = 5  # páginas por lista geral (Shopee)
FETCH_DELAY = 1.0  # pausa entre consultas à Shopee (mais lenta: a Shopee devolveu muitos "System Error" com 0,4 s)
RAKUTEN_PAGE_SIZE = 100
RAKUTEN_MAX_FAIL_STREAK = 3  # depois de 3 falhas seguidas, desiste da Rakuten nesta rodagem
STATE = {"fetch_errors": 0, "rakuten_fail_streak": 0, "rakuten_down": False}


def unwrap_error(exc: Exception) -> Exception:
    """Se for um RetryError do tenacity, revela a exceção real escondida dentro dele."""
    if type(exc).__name__ == "RetryError":
        try:
            return exc.last_attempt.exception()
        except Exception:
            pass
    return exc


# ------------------------------------------------------------ Shopee: busca
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
        for item in fetch_pool(shopee, keyword=keyword, sort_type=ShopeeClient.SORT_RELEVANCE, pages=BRAND_PAGES):
            pool.setdefault(item["itemId"], item)
    for shop_id in cfg["shop_ids"]:
        for item in fetch_pool(shopee, shop_id=shop_id, sort_type=ShopeeClient.SORT_ITEM_SOLD_DESC, pages=BRAND_PAGES):
            item["_from_brand_shop"] = True  # produtos da loja da marca dispensam o nome citar a marca
            pool[item["itemId"]] = item
    return list(pool.values())


def collect_home_pool(shopee) -> list[dict]:
    pool: dict = {}
    for keyword in selector.HOME_KEYWORDS:
        for item in fetch_pool(shopee, keyword=keyword, sort_type=ShopeeClient.SORT_ITEM_SOLD_DESC, pages=selector.HOME_PAGES):
            item.setdefault("_term", keyword)
            pool.setdefault(item["itemId"], item)
    return list(pool.values())


def collect_general_pools(shopee) -> dict[str, list[dict]]:
    sold = fetch_pool(shopee, sort_type=ShopeeClient.SORT_ITEM_SOLD_DESC, pages=GENERAL_PAGES)
    commission = fetch_pool(shopee, sort_type=ShopeeClient.SORT_COMMISSION_DESC, pages=GENERAL_PAGES)
    union = {item["itemId"]: item for item in sold + commission}
    return {"desconto": list(union.values()), "vendas": sold, "comissao": commission}


# ----------------------------------------------------------- Rakuten: busca
def rakuten_failed(exc: Exception, where: str) -> None:
    """Conta a falha; depois de várias seguidas, a Rakuten é abandonada nesta rodagem."""
    STATE["fetch_errors"] += 1
    STATE["rakuten_fail_streak"] += 1
    print(f"[AVISO] Rakuten ({where}): {unwrap_error(exc)}")
    if STATE["rakuten_fail_streak"] >= RAKUTEN_MAX_FAIL_STREAK and not STATE["rakuten_down"]:
        STATE["rakuten_down"] = True
        print("[AVISO] Rakuten parece indisponível (token ou limite): pulando o resto das buscas dela nesta rodagem.")


def fetch_rakuten_term(rakuten, advertiser: dict, term: str, pages: int | None = None) -> list[dict]:
    items: list[dict] = []
    for page in range(1, (pages or advertiser["pages"]) + 1):
        if STATE["rakuten_down"]:
            return items
        try:
            batch = rakuten.search_products(advertiser["mid"], term, page=page)
            if not batch and page == 1 and rk.norm(term) != term:
                batch = rakuten.search_products(advertiser["mid"], rk.norm(term), page=page)  # sem acento
            STATE["rakuten_fail_streak"] = 0
        except Exception as exc:
            rakuten_failed(exc, f"{advertiser['name']}, '{term}', página {page}")
            break
        items.extend(batch)
        if len(batch) < RAKUTEN_PAGE_SIZE:
            break
    return items


def build_rakuten_products(rakuten, key: str, blocked_ids: set[str], used: set[str], coupons: list[dict]):
    chosen, total_pool, total_passed = [], 0, 0
    for advertiser in rk.ADVERTISERS[key]:
        pool: list[dict] = []
        for term in advertiser["terms"]:
            pool.extend(fetch_rakuten_term(rakuten, advertiser, term))
        # Campanhas de comissão especial ativas agora: entram primeiro no bloco
        campaign_offers: list[dict] = []
        for campaign in rk.active_campaigns(advertiser["mid"], datetime.now(timezone.utc)):
            extra: list[dict] = []
            for term in campaign["terms"]:
                extra.extend(fetch_rakuten_term(rakuten, advertiser, term, pages=1))
            found = rk.pick_campaign(extra, advertiser, campaign, blocked_ids, used)
            print(f"     campanha de comissão '{campaign['name']}': buscados={len(extra)} escolhidos={len(found)}")
            campaign_offers.extend(found)
            pool.extend(extra)

        # Os demais, pelos de maior nota (campanhas já ocupam parte do total)
        scored, candidates = rk.pick_scored(
            pool, advertiser, blocked_ids, used,
            total=advertiser["total"] - len(campaign_offers), preselected=campaign_offers,
        )
        sneakers = sum(1 for o in scored if rk.detect_category(o["productName"]) == "tenis")
        with_discount = sum(1 for o in scored if o.get("priceDiscountRate"))
        print(
            f"   - {advertiser['name']}: buscados={len(pool)} candidatos={candidates} "
            f"escolhidos={len(scored)} (máx. {advertiser['total']}; tênis={sneakers}, "
            f"com desconto no feed={with_discount})"
        )
        if advertiser.get("favorites"):
            count = lambda brand: sum(1 for o in campaign_offers + scored if rk.detect_brand(o["productName"]) == brand)
            print("     marcas favoritas: " + ", ".join(f"{b}={count(b)}" for b in advertiser["favorites"]))
        picked = campaign_offers + scored
        passed = candidates
        with_coupon = rk.attach_coupons(picked, coupons)
        if coupons:
            print(f"     cupons ligados a produtos: {with_coupon} de {len(picked)}")
        chosen.extend(picked)
        total_pool += len(pool)
        total_passed += passed
    return chosen, total_pool, total_passed


def load_rakuten_coupons(rakuten) -> list[dict]:
    """Cupons válidos que dá para ligar a um produto (loja inteira ou marca)."""
    if STATE["rakuten_down"]:
        return []
    try:
        coupons = rakuten.list_coupons()
        STATE["rakuten_fail_streak"] = 0
    except Exception as exc:
        rakuten_failed(exc, "cupons")
        return []
    usable = rk.parse_coupons_for_products(coupons)
    print(f"[INFO] Rakuten: {len(coupons)} cupom(ns) no feed, {len(usable)} aplicável(is) a produtos.")
    return usable


def top_up_shopee(plan, general_pools, blocked_ids: set[str], used: set[str], blocks) -> None:
    """Se as marcas não completarem a cota (ex.: Wepink vazia), o que faltar vai pro top desconto."""
    shopee_keys = {key for kind, key, _ in blocks if kind == "shopee"}
    if general_pools is None or shopee_keys != {key for key, _ in selector.BLOCKS}:
        return  # só quando todos os blocos da Shopee rodam
    total = sum(len(offers) for key, _, offers in plan if key in shopee_keys and key != selector.HOME_KEY)
    missing = selector.SHOPEE_TARGET - total
    if missing <= 0:
        return
    extra, _ = selector.pick_general(general_pools["desconto"], "desconto", blocked_ids, used, count=missing)
    for key, _, offers in plan:
        if key == "desconto":
            offers.extend(extra)
    print(f"[INFO] Shopee: {total} de {selector.SHOPEE_TARGET}; reforço de {len(extra)} no top desconto.")


# ------------------------------------------------------------------- plano
def resolve_blocks(only: set[str] | None, include_rakuten: bool):
    shopee_blocks = [("shopee", key, label) for key, label in selector.BLOCKS]
    rakuten_blocks = [("rakuten", key, label) for key, label in rk.RAKUTEN_BLOCKS]
    if only:
        return [block for block in shopee_blocks + rakuten_blocks if block[1] in only]
    return shopee_blocks + (rakuten_blocks if include_rakuten else [])


def build_plan(shopee, blocks, blocked_ids: set[str], dry_run: bool):
    from clients.rakuten_client import RakutenClient

    used: set[str] = set()
    plan = []
    general_pools = None
    rakuten = None
    rakuten_coupons = None
    rakuten_warned = False

    for kind, key, label in blocks:
        if kind == "shopee":
            if key == selector.HOME_KEY:
                pool = collect_home_pool(shopee)
                picked, passed = selector.pick_home(pool, blocked_ids, used)
                wanted = selector.HOME_COUNT
            elif key in selector.BRANDS:
                pool = collect_brand_pool(shopee, key)
                picked, passed = selector.pick_brand(pool, key, blocked_ids, used)
                wanted = selector.BRAND_COUNT
            else:
                if general_pools is None:
                    general_pools = collect_general_pools(shopee)
                pool = general_pools[key]
                picked, passed = selector.pick_general(pool, key, blocked_ids, used)
                wanted = selector.GENERAL_COUNTS[key]
            print(f"[BLOCO {label}] buscados={len(pool)} passaram_nos_filtros={passed} escolhidos={len(picked)}")
            if len(picked) < wanted:
                print(f"[AVISO] {label}: só {len(picked)} de {wanted} (poucas ofertas boas e novas agora).")
            plan.append((key, label, picked))
            continue

        # ---- Rakuten ----
        if not settings.RAKUTEN_ENABLED:
            if not rakuten_warned:
                STATE["fetch_errors"] += 1
                print("[AVISO] Rakuten sem credenciais (RAKUTEN_TOKEN_KEY e RAKUTEN_ACCOUNT_ID). Pulando a Rakuten.")
                rakuten_warned = True
            continue
        if rakuten is None:
            rakuten = RakutenClient()

        if rakuten_coupons is None:
            rakuten_coupons = load_rakuten_coupons(rakuten)
        print(f"[BLOCO {label}]")
        picked, pool_size, passed = build_rakuten_products(rakuten, key, blocked_ids, used, rakuten_coupons)
        print(f"[BLOCO {label}] buscados={pool_size} passaram_nos_filtros={passed} escolhidos={len(picked)}")
        plan.append((key, label, picked))
    top_up_shopee(plan, general_pools, blocked_ids, used, blocks)
    return plan


# ------------------------------------------------------------------- envio
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
            caption = format_post_caption(offer, settings.WHATSAPP_GROUP_LINK, settings.TELEGRAM_GROUP_LINK)
            photo = offer.get("imageUrl")
            discount = offer.get("priceDiscountRate")
            tag = f" ({discount}% OFF)" if discount else ""

            if dry_run:
                score = f" | nota {offer['_score']}" if "_score" in offer else ""
                print(f"\n----- [{label}]{tag}{score} | loja: {offer.get('shopName')} -----")
                print(caption)
                continue

            try:
                how = telegram.send_post(photo, caption, silent=settings.TELEGRAM_SILENT)
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
                        header_image_url=photo,
                        language_code=settings.WHATSAPP_TEMPLATE_LANGUAGE,
                    )
                except Exception as exc:
                    print(f"[AVISO] WhatsApp falhou: {unwrap_error(exc)}")

            sent += 1
            time.sleep(settings.SEND_DELAY_SECONDS)
    return sent


# --------------------------------------------------------------- principal
def run(only: set[str] | None = None, dry_run: bool = False, include_rakuten: bool = False) -> int:
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
    blocks = resolve_blocks(only, include_rakuten)
    plan = build_plan(shopee, blocks, blocked_ids, dry_run)
    total = sum(len(offers) for _, _, offers in plan)
    print(f"[INFO] {total} oferta(s) escolhida(s) nesta rodagem.")

    sent = send_plan(plan, dry_run)
    if dry_run:
        print("\n[FIM] Simulação: nada foi enviado nem gravado.")
        return 0

    if STATE["fetch_errors"]:
        print(f"[AVISO] {STATE['fetch_errors']} busca(s) falharam nesta rodagem (erro da Shopee/Rakuten): alguns blocos podem ter vindo com menos ofertas.")
    print(f"[FIM] {sent} de {total} oferta(s) postada(s) no Telegram.")
    if total == 0 and STATE["fetch_errors"]:
        return 1  # as buscas falharam e nada foi escolhido: o GitHub deve marcar a rodagem como falha
    if total > 0 and sent == 0:
        return 1  # nenhum envio funcionou
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Bot de ofertas Shopee e Rakuten -> Telegram")
    parser.add_argument("--dry-run", action="store_true", help="só mostra os posts, não envia nem grava")
    parser.add_argument("--rakuten", action="store_true", help="inclui os blocos da Rakuten")
    parser.add_argument("--only", default="", help="blocos separados por vírgula (ex: casa,vendas,netshoes)")
    args = parser.parse_args(argv)

    valid = {key for key, _ in selector.BLOCKS} | {key for key, _ in rk.RAKUTEN_BLOCKS}
    only = {part.strip().lower() for part in args.only.split(",") if part.strip()}
    unknown = only - valid
    if unknown:
        print(f"Bloco(s) desconhecido(s): {', '.join(sorted(unknown))}. Opções: {', '.join(sorted(valid))}")
        return 2

    return run(only or None, args.dry_run, args.rakuten)


if __name__ == "__main__":
    sys.exit(main())
