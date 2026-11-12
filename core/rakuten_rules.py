"""
Regras da Rakuten (sem rede, fáceis de testar e de ajustar).

Anunciantes liberados: os 8 em que você está aprovado no Brasil e já validou
para divulgação em grupos. Para liberar outro, adicione em ADVERTISERS.

Como os produtos são escolhidos: cada produto que passa nos filtros recebe uma
NOTA (veja score_product) e entram os de maior nota, com variedade: tênis por
marca, o resto por categoria. Tudo que dá para ajustar está nesta seção.
"""
import hashlib
import math
import re
import statistics
import unicodedata
from datetime import datetime, timezone

# ------------------------------------------------------------------ ajustes
MAX_DISCOUNT = 75        # desconto real acima disso é suspeito: o produto é descartado
MIN_REAL_DISCOUNT = 10   # abaixo disso o desconto não conta pontos

# Termos de busca (a Rakuten não aceita: & = ? { } \ ( ) [ ] - ; ~ | $ ! > < * %)
CATEGORY_TERMS = [
    "tênis", "chuteira", "camisa", "camiseta", "moletom",
    "jaqueta", "bermuda", "legging", "mochila", "relógio",
]
BRAND_TERMS = [
    "nike", "adidas", "puma", "asics", "under armour", "olympikus", "mizuno",
    "umbro", "fila", "new balance", "havaianas", "kenner", "oakley", "reebok",
    "vans", "lacoste", "everlast", "reserva", "kappa", "mormaii",
    "calvin klein", "converse", "osklen",
]
OTHER_CATEGORIES = [  # além de tênis
    "camiseta", "camisa", "moletom", "jaqueta", "bermuda",
    "legging", "mochila", "relógio", "chuteira",
]

# Marcas favoritas: cota mínima por loja grande, dentro do total (se houver produtos bons).
# Cada cota segue o foco em tênis (70%); o resto da cota vem de outras categorias.
FAVORITE_BRANDS = {"nike": 12, "adidas": 12}
FAVORITE_CATEGORIES = ["camiseta", "camisa", "moletom", "jaqueta", "bermuda", "legging", "mochila"]

# Modelos de Nike e Adidas que o público procura (buscas extras, para ter mais produtos deles)
FAVORITE_MODEL_TERMS = [
    "nike air max", "nike pegasus", "nike revolution", "nike downshifter", "nike air force",
    "adidas samba", "adidas campus", "adidas superstar", "adidas lite racer", "adidas adi365",
]

# Para as lojas grandes: as categorias + "tênis <marca>" (traz tênis de cada marca) +
# "<categoria> <marca favorita>" (mais roupas de Nike e Adidas) + modelos favoritos
BIG_TERMS = (
    CATEGORY_TERMS
    + [f"tênis {brand}" for brand in BRAND_TERMS]
    + [f"{category} {brand}" for brand in FAVORITE_BRANDS for category in FAVORITE_CATEGORIES]
    + FAVORITE_MODEL_TERMS
)

# Público: só o infantil fica de fora (feminino e unissex entram)
EXCLUDED_AUDIENCE_WORDS = ("infantil", "kids", "menino", "menina", "bebe", "juvenil")

# "Preço ok" por categoria (R$, no preço do feed). Fora da faixa, o produto não entra.
PRICE_RANGES = {
    "tenis": (120, 350), "camiseta": (45, 130), "camisa": (45, 130),
    "moletom": (90, 280), "jaqueta": (90, 280), "bermuda": (50, 150),
    "legging": (50, 150), "mochila": (60, 200), "relogio": (80, 300),
    "chuteira": (120, 350),
}
# As lojas de time vendem camisas oficiais e itens licenciados, mais caros: faixas maiores
TEAM_PRICE_RANGES = {
    "tenis": (120, 450), "camiseta": (40, 260), "camisa": (60, 320),
    "moletom": (90, 350), "jaqueta": (90, 400), "bermuda": (50, 220),
    "legging": (50, 200), "mochila": (60, 250), "relogio": (80, 350),
    "chuteira": (120, 600),
}
RANGES = {"default": PRICE_RANGES, "team": TEAM_PRICE_RANGES}

# Modelos "queridinhos": ganham pontos. Use o nome como aparece no produto; edite à vontade.
POPULAR_MODELS = [
    "lite racer", "samba", "campus", "superstar", "stan smith", "gazelle", "adi365",
    "adizero", "air max", "pegasus", "revolution", "downshifter", "gel nimbus",
    "gel kayano", "gt 2160", "fresh foam", "574", "530", "1000", "327", "wave",
    "caven", "old skool", "sk8", "chuck taylor", "all star", "athletics", "corre",
]

# Pesos da nota
POPULAR_POINTS = 4        # modelo queridinho
BRAND_POINTS = 2          # marca conhecida
DISCOUNT_POINTS_MAX = 6   # desconto real: 1 ponto a cada 10%, até este máximo
GAP_MIN = 0.15            # quanto abaixo da mediana dos parecidos (marca + categoria) conta
GAP_POINTS_MAX = 4        # abaixo da mediana: 1 ponto a cada 10%, até este máximo
LOW_PRICE_POINTS = 1      # preço na metade de baixo da faixa
MIN_GROUP_FOR_MEDIAN = 5  # produtos parecidos necessários para calcular a mediana


def _store(mid: str, name: str, total: int, *, big: bool) -> dict:
    return {
        "mid": mid, "name": name, "total": total,
        "pages": 2 if big else 1,
        "terms": BIG_TERMS if big else CATEGORY_TERMS,
        "sneaker_share": 0.7 if big else 0,   # 70% tênis nas lojas grandes
        "favorites": FAVORITE_BRANDS if big else {},  # cota de Nike e Adidas só nas lojas grandes
        "require_brand": big,                 # marca conhecida obrigatória só nas lojas grandes
        "ranges": "default" if big else "team",
    }


ADVERTISERS = {
    # Os mais cobiçados: 40 produtos cada (12 Nike + 12 Adidas dentro do total)
    "netshoes": [_store("43984", "Netshoes", 40, big=True)],
    "zattini": [_store("43985", "Zattini", 40, big=True)],
    # Lojas de time: 2 produtos cada (o Cruzeiro fica com 5)
    "times": [
        _store("54199", "LojaNBA", 2, big=False),
        _store("54196", "Santos Store", 2, big=False),
        _store("54162", "São Store", 2, big=False),
        _store("54200", "Shop Timao", 2, big=False),
        _store("54198", "Cruzeiro Store", 5, big=False),
        _store("54197", "Inter Store", 2, big=False),
    ],
}

RAKUTEN_BLOCKS = [
    ("netshoes", "RAKUTEN - NETSHOES"),
    ("zattini", "RAKUTEN - ZATTINI"),
    ("times", "RAKUTEN - LOJAS DE TIME"),
]


# ---------------------------------------------------------------- utilidades
def norm(text) -> str:
    text = unicodedata.normalize("NFKD", " ".join(str(text or "").split()))
    return text.encode("ascii", "ignore").decode().lower()


def product_key(mid: str, name: str) -> str:
    """Identificador estável: o mesmo produto em tamanhos diferentes tem o mesmo nome."""
    digest = hashlib.sha1(f"{mid}|{norm(name)}".encode()).hexdigest()[:16]
    return f"rk:{mid}:{digest}"


def discount_pct(product: dict) -> int:
    price, sale = product.get("price"), product.get("sale")
    if price and sale and 0 < sale < price:
        return round((price - sale) / price * 100)
    return 0


def real_discount(product: dict) -> int:
    """Desconto que o feed informa (preço promocional menor que o normal), se for relevante."""
    pct = discount_pct(product)
    return pct if pct >= MIN_REAL_DISCOUNT else 0


def effective_price(product: dict):
    """Preço que o cliente paga: o promocional (se for menor) ou o preço normal."""
    price, sale = product.get("price"), product.get("sale")
    if price and sale and 0 < sale < price:
        return sale
    return price


BRAND_ALIASES = {"under armor": "under armour"}  # grafias que aparecem nos textos
_BRANDS_NORM = sorted(
    [(norm(b), b) for b in BRAND_TERMS] + [(norm(a), b) for a, b in BRAND_ALIASES.items()],
    key=lambda t: -len(t[0]),
)


def detect_brand(name: str):
    """Marca conhecida citada no nome (palavra inteira), ou None."""
    text = norm(name)
    for brand_norm, brand in _BRANDS_NORM:
        if re.search(rf"\b{re.escape(brand_norm)}\b", text):
            return brand
    return None


def detect_category(name: str):
    """'tenis' ou uma das outras categorias citadas no nome, ou None."""
    text = norm(name)
    if "tenis" in text:
        return "tenis"
    for category in OTHER_CATEGORIES:
        if norm(category) in text:
            return norm(category)
    return None


def to_offer(key: str, product: dict, merchant: str) -> dict:
    """Post com preço "De" e "Por" (o feed informa o desconto)."""
    return {
        "itemId": key,
        "productName": product["name"],
        "priceMin": product["sale"],
        "original_price": product["price"],  # preço "De" real (não calculado)
        "priceDiscountRate": discount_pct(product),
        "offerLink": product["link"],
        "imageUrl": product.get("image") or None,
        "shopName": merchant,
    }


def to_offer_no_discount(key: str, product: dict, merchant: str) -> dict:
    """Post sem linha 'De' (o feed não informa promoção): só 'Por R$ X'."""
    return {
        "itemId": key,
        "productName": product["name"],
        "priceMin": effective_price(product),
        "priceDiscountRate": 0,
        "offerLink": product["link"],
        "imageUrl": product.get("image") or None,
        "shopName": merchant,
    }


def build_offer(key: str, product: dict, advertiser: dict, score: float) -> dict:
    make = to_offer if real_discount(product) else to_offer_no_discount
    offer = make(key, product, advertiser["name"])
    offer["_mid"] = advertiser["mid"]
    offer["_score"] = score
    return offer


# ----------------------------------------------------- escolha por nota
def is_excluded_audience(name: str) -> bool:
    text = _alnum(name)
    return any(_has_token(text, word) for word in EXCLUDED_AUDIENCE_WORDS)


def is_candidate(product: dict, advertiser: dict) -> bool:
    """Filtros que tiram o produto da disputa (antes da nota)."""
    if product.get("price_cur") != "BRL" or not product.get("link") or not product.get("name"):
        return False
    price = effective_price(product)
    if not price or price <= 0:
        return False
    name = product["name"]
    if is_excluded_audience(name):
        return False
    category = detect_category(name)
    if not category:
        return False
    if advertiser.get("require_brand") and not detect_brand(name):
        return False
    low, high = RANGES[advertiser["ranges"]][category]
    if not low <= price <= high:
        return False
    return discount_pct(product) <= MAX_DISCOUNT


def group_medians(products: list[dict]) -> dict:
    """Preço mediano dos parecidos (marca + categoria), quando há produtos suficientes."""
    groups: dict = {}
    for p in products:
        groups.setdefault((detect_brand(p["name"]), detect_category(p["name"])), []).append(effective_price(p))
    return {g: statistics.median(prices) for g, prices in groups.items() if len(prices) >= MIN_GROUP_FOR_MEDIAN}


def score_product(product: dict, advertiser: dict, medians: dict) -> float:
    """
    Nota do produto (maior = melhor):
      + modelo queridinho, + marca conhecida,
      + desconto real do feed (se houver),
      + preço bem abaixo dos parecidos (mesma marca e categoria),
      + preço na metade de baixo da faixa "ok" da categoria.
    """
    name = product["name"]
    price = effective_price(product)
    brand, category = detect_brand(name), detect_category(name)
    text = _alnum(name)

    points = 0.0
    if any(_has_token(text, model) for model in POPULAR_MODELS):
        points += POPULAR_POINTS
    if brand:
        points += BRAND_POINTS
    points += min(real_discount(product) / 10, DISCOUNT_POINTS_MAX)

    median = medians.get((brand, category))
    if median and price < median:
        gap = (median - price) / median
        if gap >= GAP_MIN:
            points += min(gap * 10, GAP_POINTS_MAX)

    low, high = RANGES[advertiser["ranges"]][category]
    if price <= (low + high) / 2:
        points += LOW_PRICE_POINTS
    return round(points, 2)


def _round_robin(groups: dict, count: int) -> list:
    """O melhor de cada grupo em rodadas (variedade), até `count`. Itens: (chave, produto, nota)."""
    if count <= 0:
        return []
    order = sorted((g for g in groups if groups[g]), key=lambda g: groups[g][0][2], reverse=True)
    chosen, rnd = [], 0
    while len(chosen) < count and any(len(groups[g]) > rnd for g in order):
        for group in order:
            if len(chosen) >= count:
                break
            if len(groups[group]) > rnd:
                chosen.append(groups[group][rnd])
        rnd += 1
    return chosen


def _pick_quota(entries: list, count: int, share: float) -> list:
    """`count` itens de uma marca (já em ordem de nota): `share` de tênis e o resto por categoria."""
    sneakers = [e for e in entries if detect_category(e[1]["name"]) == "tenis"]
    others: dict = {}
    for entry in entries:
        category = detect_category(entry[1]["name"])
        if category != "tenis":
            others.setdefault(category, []).append(entry)
    chosen = sneakers[: math.ceil(count * share)]
    chosen += _round_robin(others, count - len(chosen))
    if len(chosen) < count:  # faltou em algum grupo: completa pelos de maior nota
        taken = {e[0] for e in chosen}
        chosen += [e for e in entries if e[0] not in taken][: count - len(chosen)]
    return chosen


def pick_scored(items, advertiser, blocked_ids, used_ids, total, preselected=()):
    """
    Até `total` produtos do anunciante, pelos de maior nota. Um post por produto (tamanhos
    diferentes têm o mesmo nome). Primeiro vêm as cotas das marcas favoritas (Nike e Adidas,
    descontando o que já foi escolhido em `preselected`, como campanhas); depois, nas lojas
    grandes, 70% de tênis (um de cada marca por rodada) e, no resto, um de cada categoria por
    rodada. Devolve (ofertas, candidatos).
    """
    if total <= 0:
        return [], 0

    pool = [p for p in items if p.get("mid") in ("", advertiser["mid"]) and is_candidate(p, advertiser)]
    pool.sort(key=effective_price)

    unique, seen_names = [], set()
    for product in pool:
        name_key = norm(product["name"])
        if name_key in seen_names:
            continue
        seen_names.add(name_key)
        key = product_key(advertiser["mid"], product["name"])
        if key in blocked_ids or key in used_ids:
            continue
        unique.append((key, product))

    medians = group_medians([p for _, p in unique])
    ranked = [(key, p, score_product(p, advertiser, medians)) for key, p in unique]
    ranked.sort(key=lambda e: (e[2], real_discount(e[1]), -effective_price(e[1])), reverse=True)

    share = advertiser.get("sneaker_share", 0)

    # 1) Cotas das marcas favoritas
    picked: list = []
    have: dict = {}
    for offer in preselected:
        brand = detect_brand(offer.get("productName", ""))
        have[brand] = have.get(brand, 0) + 1
    for brand, quota in advertiser.get("favorites", {}).items():
        need = min(quota - have.get(brand, 0), total - len(picked))
        if need > 0:
            taken = {e[0] for e in picked}
            entries = [e for e in ranked if detect_brand(e[1]["name"]) == brand and e[0] not in taken]
            picked += _pick_quota(entries, need, share or 0.7)

    # 2) O resto, pelos de maior nota
    taken = {e[0] for e in picked}
    rest = [e for e in ranked if e[0] not in taken]
    sneakers, others = {}, {}
    for entry in rest:
        category = detect_category(entry[1]["name"])
        if share and category == "tenis":
            sneakers.setdefault(detect_brand(entry[1]["name"]), []).append(entry)
        else:
            others.setdefault(category, []).append(entry)

    remaining = total - len(picked)
    extra = _round_robin(sneakers, math.ceil(remaining * share)) if share else []
    extra += _round_robin(others, remaining - len(extra))
    if len(extra) < remaining:  # faltou em algum grupo: completa pelos de maior nota que sobraram
        done = {e[0] for e in extra}
        extra += [e for e in rest if e[0] not in done][: remaining - len(extra)]
    picked += extra

    offers = []
    for key, product, score in picked:
        used_ids.add(key)
        offers.append(build_offer(key, product, advertiser, score))
    return offers, len(unique)


# ------------------------------------------- campanhas de comissão especial
# Ofertas de comissão (painel da Rakuten > anunciante > Ofertas): em janelas curtas a
# Netshoes paga 15% (contra 5% da base) por modelos específicos. O bot dá prioridade a
# esses modelos enquanto a campanha está ativa. A comissão NÃO aparece no post.
# Para incluir uma campanha nova, copie um bloco abaixo (datas em UTC; Brasília = UTC-3).
CAMPAIGN_LIMIT = 5  # produtos (cores/modelos) por campanha ativa


def _utc(month: int, day: int) -> datetime:
    return datetime(2026, month, day, 3, 0, tzinfo=timezone.utc)  # 00:00 em Brasília


CAMPAIGNS = [
    {"mid": "43984", "name": "Asics GT-2160", "terms": ["asics gt 2160"],
     "all": ["asics"], "any": ["gt 2160", "gt2160"], "start": _utc(11, 3), "end": _utc(11, 5)},
    {"mid": "43984", "name": "Adidas Campus", "terms": ["adidas campus"],
     "all": ["adidas", "campus"], "any": [], "start": _utc(11, 5), "end": _utc(11, 7)},
    {"mid": "43984", "name": "Adidas Superstar", "terms": ["adidas superstar"],
     "all": ["adidas", "superstar"], "any": [], "start": _utc(11, 7), "end": _utc(11, 9)},
    {"mid": "43984", "name": "New Balance 1000", "terms": ["new balance 1000"],
     "all": ["new balance"], "any": ["1000"], "start": _utc(11, 9), "end": _utc(11, 11)},
    {"mid": "43984", "name": "New Balance 530", "terms": ["new balance 530"],
     "all": ["new balance"], "any": ["530"], "start": _utc(11, 11), "end": _utc(11, 13)},
]


def _alnum(text) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", norm(text)).split())


def _has_token(text: str, token: str) -> bool:
    """O termo aparece como palavra inteira (aceita 'gt 2160' e 'gt2160', mas não '5300' para '530')."""
    token = _alnum(token)
    if re.search(rf"\b{re.escape(token)}\b", text):
        return True
    squeezed = token.replace(" ", "")
    return squeezed != token and bool(re.search(rf"\b{re.escape(squeezed)}\b", text))


def active_campaigns(mid: str, now=None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    return [c for c in CAMPAIGNS if c["mid"] == mid and c["start"] <= now < c["end"]]


def matches_campaign(name: str, campaign: dict) -> bool:
    """O nome tem todos os termos obrigatórios e (se houver) pelo menos um dos alternativos."""
    text = _alnum(name)
    if not all(_has_token(text, token) for token in campaign["all"]):
        return False
    return not campaign["any"] or any(_has_token(text, token) for token in campaign["any"])


def pick_campaign(items, advertiser, campaign, blocked_ids, used_ids, limit=CAMPAIGN_LIMIT):
    """Produtos da campanha (cores diferentes = nomes diferentes), do mais barato ao mais caro."""
    pool = [
        p for p in items
        if p.get("mid") in ("", advertiser["mid"]) and p.get("price_cur") == "BRL"
        and effective_price(p) and p.get("link") and p.get("name")
        and matches_campaign(p["name"], campaign)
    ]
    pool.sort(key=effective_price)

    offers, seen_names = [], set()
    for product in pool:
        name_key = norm(product["name"])
        key = product_key(advertiser["mid"], product["name"])
        if name_key in seen_names or key in blocked_ids or key in used_ids:
            continue
        seen_names.add(name_key)
        offer = to_offer_no_discount(key, product, advertiser["name"])
        offer["_mid"] = advertiser["mid"]
        offer["_campaign"] = campaign["name"]
        used_ids.add(key)
        offers.append(offer)
        if len(offers) >= limit:
            break
    return offers


# --------------------------------------------- cupons ligados a produtos
# O feed de cupons da Rakuten é só texto (sem lista de produtos). Ligamos a um
# produto apenas o que o texto deixa claro: cupom da loja inteira ou de uma marca.
_NOT_FOR_PRODUCTS = ("leve ", "mimo", "brinde", "acima de", "frete")  # dependem de lista/carrinho
_CODE_IN_TEXT = re.compile(r"(?i:cupom)\s*[:\-]?\s*([A-Z0-9]{4,20})\b")


def parse_coupon(coupon: dict, now=None):
    """Cupom validado e interpretado, ou None se não dá para ligar a um produto."""
    now = now or datetime.now(timezone.utc)
    if (coupon["start"] and coupon["start"] > now) or (coupon["end"] and coupon["end"] < now):
        return None
    desc = coupon["desc"]
    text = norm(desc)
    if any(word in text for word in _NOT_FOR_PRODUCTS):
        return None

    match = re.search(r"(\d{1,2})\s*%", desc)
    percent = int(match.group(1)) if match else None
    code = coupon["code"]
    if not code:
        found = _CODE_IN_TEXT.search(desc)
        code = found.group(1) if found else ""
    if not percent and not code:
        return None

    return {
        "adv_id": coupon["adv_id"],
        "brand": detect_brand(desc),
        "percent": percent,
        "code": code,
        "up_to": bool(re.search(r"\bate\s+\d", text)),
        "first_purchase": "primeira compra" in text,
        "conditions": "*" in desc or " lista" in text,
    }


def parse_coupons_for_products(coupons, now=None) -> list[dict]:
    parsed = [parse_coupon(c, now) for c in coupons]
    return [c for c in parsed if c]


def coupon_line(coupon: dict) -> str:
    percent = f"{'até ' if coupon['up_to'] else ''}{coupon['percent']}% OFF" if coupon["percent"] else ""
    note = " (1ª compra)" if coupon["first_purchase"] else " (*confira as condições)" if coupon["conditions"] else ""
    brand = coupon["brand"].title() if coupon["brand"] else ""
    if coupon["code"]:
        who = f" ({brand})" if brand else ""
        return f"🎫 Cupom {coupon['code']}{who}: {percent}{note}" if percent else f"🎫 Cupom {coupon['code']}{who}{note}"
    return f"🏷️ Promoção {brand or 'da loja'}: {percent}{note}"


def coupon_lines_for(offer: dict, coupons: list[dict]) -> list[str]:
    """Até 2 linhas: o melhor cupom da loja e, se houver, o da marca do produto."""
    mine = [c for c in coupons if c["adv_id"] == offer.get("_mid")]
    brand = detect_brand(offer.get("productName", ""))
    best = lambda group: max(group, key=lambda c: (c["percent"] or 0, bool(c["code"])))

    lines = []
    store = [c for c in mine if not c["brand"]]
    if store:
        lines.append(coupon_line(best(store)))
    of_brand = [c for c in mine if c["brand"] and c["brand"] == brand]
    if of_brand:
        lines.append(coupon_line(best(of_brand)))
    return lines


def attach_coupons(offers: list[dict], coupons: list[dict]) -> int:
    """Coloca as linhas de cupom nas ofertas aplicáveis. Devolve quantas receberam."""
    attached = 0
    for offer in offers:
        lines = coupon_lines_for(offer, coupons)
        if lines:
            offer["coupon_lines"] = lines
            attached += 1
    return attached
