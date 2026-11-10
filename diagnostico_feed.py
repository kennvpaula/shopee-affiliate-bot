"""
Diagnostico SOMENTE LEITURA: por que os produtos da Netshoes e da Zattini nao
passam nos filtros? Nao envia nada pro Telegram e nao grava no Supabase.

Coloque este arquivo na pasta do projeto (junto do main.py) e rode:
    python diagnostico_feed.py

Espere o main.py terminar antes (os dois usam o limite de chamadas da Rakuten).
O resultado tambem fica em diagnostico_feed.txt.
"""
import time
from collections import Counter

from clients.rakuten_client import RakutenClient
from core import rakuten_rules as rk

ADVERTISERS = [("Netshoes", "43984"), ("Zattini", "43985")]
TERMS = ["tênis", "camisa", "nike", "adidas"]
LINES = []


def out(text=""):
    print(text)
    LINES.append(str(text))


def reason(p):
    """Primeiro motivo que reprova o produto (ou 'APROVADO')."""
    if p["price_cur"] != "BRL" or p["sale_cur"] not in ("", "BRL"):
        return "moeda diferente de BRL"
    price, sale = p["price"], p["sale"]
    if not price or not sale or price <= 0 or sale <= 0:
        return "sem preco valido"
    if sale > price:
        return "preco promocional MAIOR que o normal"
    if sale == price:
        return "preco promocional IGUAL ao normal (sem promocao)"
    if sale < rk.MIN_SALE_PRICE:
        return f"promocional abaixo de R$ {rk.MIN_SALE_PRICE:.0f}"
    if not p["link"] or not p["name"]:
        return "sem link ou nome"
    pct = rk.discount_pct(p)
    if pct < rk.MIN_DISCOUNT:
        low = pct // 10 * 10
        return f"desconto de {low}% a {low + 9}% (abaixo do minimo de {rk.MIN_DISCOUNT}%)"
    if pct > rk.MAX_DISCOUNT:
        return f"desconto acima do maximo de {rk.MAX_DISCOUNT}%"
    return "APROVADO"


def main():
    client = RakutenClient()
    for name, mid in ADVERTISERS:
        out("\n" + "=" * 64 + f"\n{name.upper()} (mid {mid})\n" + "=" * 64)
        items = []
        for term in TERMS:
            for page in (1, 2):
                try:
                    batch = client.search_products(mid, term, page=page)
                except Exception as exc:
                    out(f"[ERRO] '{term}' pagina {page}: {exc}")
                    break
                items.extend(batch)
                if len(batch) < 100:
                    break
        out(f"{len(items)} itens lidos ({len(TERMS)} termos: {', '.join(TERMS)}).")
        if not items:
            continue

        reasons = Counter(reason(p) for p in items)
        out("\nMotivo pelo qual cada item passou ou foi barrado:")
        for text, qty in reasons.most_common():
            out(f"  {qty:5d}  {text}")

        discounted = [p for p in items if p["price"] and p["sale"] and p["sale"] < p["price"]]
        out(f"\nItens com preco promocional menor que o normal: {len(discounted)} de {len(items)}")
        for p in sorted(discounted, key=rk.discount_pct, reverse=True)[:5]:
            out(f"  {rk.discount_pct(p)}% | R$ {p['price']} -> R$ {p['sale']} | {p['name'][:60]}")

        out("\nExemplos de itens (nome | price | saleprice):")
        for p in items[:5]:
            out(f"  {p['name'][:55]} | {p['price']} | {p['sale']}")
        time.sleep(0.5)

    with open("diagnostico_feed.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(LINES))
    print("\nResultado salvo em diagnostico_feed.txt")


if __name__ == "__main__":
    main()
