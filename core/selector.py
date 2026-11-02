"""
Regras de escolha das ofertas (sem rede, fácil de testar e de ajustar).
Mexa nas constantes abaixo para deixar o filtro mais rígido ou mais solto.
"""
import unicodedata

# ---------------------------------------------------------------- ajustes
BRAND_COUNT = 5      # ofertas por marca em cada rodagem
GENERAL_COUNT = 3    # ofertas por lista geral (desconto, vendas, comissão)

MAX_DISCOUNT = 60    # acima disso o desconto é tratado como suspeito (preço "de" inflado)
BRAND_MIN_DISCOUNT = 5
GENERAL_MIN_DISCOUNT = {"desconto": 20, "vendas": 15, "comissao": 10}

MIN_RATING_TRUSTED = 4.5   # loja oficial / preferred
MIN_RATING_COMMON = 4.7    # vendedor comum
MIN_SALES_COMMON = 20      # vendas mínimas exigidas de vendedor comum
MAX_PER_SHOP = 2           # no máximo N ofertas da mesma loja por bloco (se houver opção)

TRUSTED_SHOP_TYPES = {1, 2, 4}  # 1 oficial, 2 preferred, 4 preferred plus

# Produtos que citam a marca mas não são o produto da marca
BLOCKED_WORDS = (
    "inspiracao", "inspirado", "inspirada", "similar", "compativel",
    "valvula", "replica", "contratipo", "dupe", "imitacao",
)

BRANDS = {
    "boticario": {
        "label": "BOTICÁRIO",
        "words": ["boticario"],
        "keywords": ["boticário", "boticario perfume", "boticario hidratante", "boticario desodorante"],
        "shop_ids": [],
    },
    "natura": {
        "label": "NATURA",
        "words": ["natura"],
        "keywords": ["natura", "natura perfume", "natura hidratante", "natura desodorante"],
        "shop_ids": [1590879011],  # Natura.Beauty (loja PREFERRED encontrada no teste)
    },
    "wepink": {
        "label": "WEPINK",
        "words": ["wepink", "we pink"],
        "keywords": ["wepink", "we pink", "wepink body splash", "wepink perfume"],
        "shop_ids": [],
    },
    "eudora": {
        "label": "EUDORA",
        "words": ["eudora"],
        "keywords": ["eudora", "eudora perfume", "eudora hidratante", "eudora body splash"],
        "shop_ids": [],
    },
}

GENERAL_LABELS = {
    "desconto": "TOP DESCONTO",
    "vendas": "TOP VENDAS",
    "comissao": "TOP COMISSÃO",
}

# Ordem em que os blocos são montados e postados
BLOCKS = [(key, cfg["label"]) for key, cfg in BRANDS.items()] + list(GENERAL_LABELS.items())


# ------------------------------------------------------------ utilidades
def norm(text) -> str:
    text = unicodedata.normalize("NFKD", str(text or ""))
    return text.encode("ascii", "ignore").decode().lower()


def _num(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def discount_of(offer: dict) -> int:
    return int(_num(offer.get("priceDiscountRate")))


def commission_of(offer: dict) -> float:
    return _num(offer.get("commissionRate"))


def sales_of(offer: dict) -> int:
    return int(_num(offer.get("sales")))


def rating_of(offer: dict) -> float:
    return _num(offer.get("ratingStar"))


def price_of(offer: dict) -> float:
    return _num(offer.get("priceMin")) or _num(offer.get("priceMax"))


def item_key(offer: dict) -> str:
    return str(offer.get("itemId"))


def is_trusted_shop(offer: dict) -> bool:
    shop_type = offer.get("shopType") or []
    if not isinstance(shop_type, list):
        shop_type = [shop_type]
    return any(t in TRUSTED_SHOP_TYPES for t in shop_type)


def has_blocked_name(offer: dict) -> bool:
    name = norm(offer.get("productName"))
    return any(word in name for word in BLOCKED_WORDS)


def mentions_brand(offer: dict, words: list[str]) -> bool:
    name = norm(offer.get("productName"))
    return any(norm(word) in name for word in words)


def is_good_offer(offer: dict, min_discount: int) -> bool:
    """Filtros de qualidade comuns a todos os blocos."""
    if not (offer.get("offerLink") or offer.get("productLink")):
        return False
    if price_of(offer) <= 0 or commission_of(offer) <= 0:
        return False
    discount = discount_of(offer)
    if discount < min_discount or discount > MAX_DISCOUNT:
        return False
    if has_blocked_name(offer):
        return False
    if is_trusted_shop(offer):
        return rating_of(offer) >= MIN_RATING_TRUSTED
    return rating_of(offer) >= MIN_RATING_COMMON and sales_of(offer) >= MIN_SALES_COMMON


def _eligible(pool, blocked_ids, used_ids, accept, min_discount) -> list[dict]:
    result, seen = [], set()
    for offer in pool:
        key = item_key(offer)
        if key in blocked_ids or key in used_ids or key in seen:
            continue
        if not accept(offer) or not is_good_offer(offer, min_discount):
            continue
        seen.add(key)
        result.append(offer)
    return result


def _take(candidates: list[dict], count: int) -> list[dict]:
    """Pega até `count` respeitando MAX_PER_SHOP; se faltar, completa sem o limite."""
    chosen, per_shop = [], {}
    for offer in candidates:
        if len(chosen) >= count:
            break
        shop = offer.get("shopId")
        if per_shop.get(shop, 0) >= MAX_PER_SHOP:
            continue
        chosen.append(offer)
        per_shop[shop] = per_shop.get(shop, 0) + 1

    if len(chosen) < count:
        picked = {id(o) for o in chosen}
        for offer in candidates:
            if len(chosen) >= count:
                break
            if id(offer) not in picked:
                chosen.append(offer)
    return chosen


# --------------------------------------------------------------- escolha
def pick_brand(pool, key, blocked_ids, used_ids, count=BRAND_COUNT):
    """Escolhe até `count` ofertas da marca. Devolve (escolhidas, qtd_que_passou_nos_filtros)."""
    words = BRANDS[key]["words"]
    accept = lambda o: bool(o.get("_from_brand_shop")) or mentions_brand(o, words)
    candidates = _eligible(pool, blocked_ids, used_ids, accept, BRAND_MIN_DISCOUNT)
    candidates.sort(key=lambda o: (discount_of(o), commission_of(o)), reverse=True)
    chosen = _take(candidates, count)
    used_ids.update(item_key(o) for o in chosen)
    return chosen, len(candidates)


_GENERAL_SORT = {
    "desconto": lambda o: (discount_of(o), sales_of(o)),
    "vendas": lambda o: (sales_of(o), discount_of(o)),
    "comissao": lambda o: (commission_of(o), discount_of(o)),
}


def pick_general(pool, key, blocked_ids, used_ids, count=GENERAL_COUNT):
    """Escolhe até `count` ofertas da lista geral (desconto, vendas ou comissao)."""
    candidates = _eligible(
        pool, blocked_ids, used_ids, lambda o: True, GENERAL_MIN_DISCOUNT[key]
    )
    candidates.sort(key=_GENERAL_SORT[key], reverse=True)
    chosen = _take(candidates, count)
    used_ids.update(item_key(o) for o in chosen)
    return chosen, len(candidates)
