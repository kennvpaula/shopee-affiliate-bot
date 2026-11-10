"""Transforma dados das ofertas (Shopee e Rakuten) em texto pronto pra postar."""

# Nomes de produto da Shopee costumam vir cheios de palavras-chave repetidas.
# Cortamos pra manter o post limpo, como nos exemplos curados à mão.
MAX_PRODUCT_NAME_LENGTH = 70


def _to_float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def format_price_brl(value) -> str:
    """Padrão brasileiro: vírgula e sempre 2 casas. 111.9 -> '111,90'. Inválido -> '?'."""
    number = _to_float(value)
    if number is None:
        return "?"
    return f"{number:.2f}".replace(".", ",")


def truncate_name(name: str, max_length: int = MAX_PRODUCT_NAME_LENGTH) -> str:
    name = name.strip()
    if len(name) <= max_length:
        return name
    return name[: max_length - 3].rstrip() + "..."


def clean_text(text: str) -> str:
    """Tira símbolos que o WhatsApp interpretaria como formatação (*, ~, _)."""
    for symbol in ("*", "~"):
        text = text.replace(symbol, "")
    text = text.replace("_", " ")
    return " ".join(text.split())


def clean_name(name: str) -> str:
    """Limpa os símbolos e corta o tamanho do nome do produto."""
    return truncate_name(clean_text(name))


def current_price(offer: dict) -> float | None:
    """Preço atual: o menor preço do anúncio (priceMin), com priceMax como reserva."""
    for key in ("priceMin", "priceMax"):
        number = _to_float(offer.get(key))
        if number and number > 0:
            return number
    return None


def compute_original_price(price: float | None, discount_rate) -> float | None:
    """
    Preço "De" calculado a partir do % de desconto que a Shopee mostra na página
    do produto (priceDiscountRate). Sem desconto, devolve None (o post não mostra a linha "De").
    É uma aproximação: pode diferir uns centavos do preço riscado da página.
    """
    rate = _to_float(discount_rate)
    if not price or not rate or rate <= 0 or rate >= 100:
        return None
    return round(price / (1 - rate / 100), 2)


def format_post_caption(
    offer: dict, whatsapp_group_link: str = "", telegram_group_link: str = ""
) -> str:
    """
    Post no modelo do WhatsApp (símbolos do WhatsApp em texto simples):

        🏁 Nome do produto

        ~De R$ 125,00~
        💵 *Por R$ 100,00*

        🎫 Cupom: CODIGO            <- só aparece se a oferta tiver cupom

        Link com desconto ↘️
        https://...

        🔥 *VAGAS NO GRUPO DO WHATSAPP NESSE LINK:*
        https://chat.whatsapp.com/...

        ✈️ *ENTRE TAMBÉM NO GRUPO DO TELEGRAM:*
        https://t.me/...
    """
    name = clean_name(offer.get("productName") or "Produto")
    price = current_price(offer)
    # Rakuten informa o preço "De" real (original_price); Shopee só dá o % de desconto
    original = _to_float(offer.get("original_price"))
    if not original or not price or original <= price:
        original = compute_original_price(price, offer.get("priceDiscountRate"))
    link = offer.get("offerLink") or offer.get("productLink") or ""

    lines = [f"🏁 {name}", ""]
    if original:
        lines.append(f"~De R$ {format_price_brl(original)}~")
    lines.append(f"💵 *Por R$ {format_price_brl(price)}*")

    coupon = offer.get("coupon_code")
    if coupon:
        lines += ["", f"🎫 Cupom: {coupon}"]
    coupon_lines = offer.get("coupon_lines") or []  # cupons da Rakuten que se aplicam ao produto
    if coupon_lines:
        lines += [""] + coupon_lines

    # Sem preço "De" não há desconto garantido: o rótulo não promete desconto
    lines += ["", "Link com desconto ↘️" if original else "Link ↘️", link]

    if whatsapp_group_link:
        lines += ["", "🔥 *VAGAS NO GRUPO DO WHATSAPP NESSE LINK:*", whatsapp_group_link]
    if telegram_group_link:
        lines += ["", "✈️ *ENTRE TAMBÉM NO GRUPO DO TELEGRAM:*", telegram_group_link]

    return "\n".join(lines)


def format_whatsapp_body_params(offer: dict) -> dict[str, str]:
    """
    Variáveis nomeadas do template aprovado do WhatsApp (só usado se o envio
    pelo WhatsApp Cloud API estiver ligado com WHATSAPP_ENABLED=true).
    """
    price = current_price(offer)
    original = compute_original_price(price, offer.get("priceDiscountRate")) or price
    return {
        "product_name": clean_name(offer.get("productName") or "Produto"),
        "original_price": format_price_brl(original),
        "discount_price": format_price_brl(price),
        "coupon_code": offer.get("coupon_code") or "-",
        "product_link": offer.get("offerLink") or offer.get("productLink") or "",
    }
