"""
Diagnostico SOMENTE LEITURA: como aparecem no feed da Netshoes os produtos que
voce quer (os que outro grupo posta) e por que o bot nao os escolheu.
Nao envia nada pro Telegram e nao grava no Supabase.

Coloque este arquivo na pasta do projeto (junto do main.py) e rode, com o venv ativo:
    python diagnostico_produtos.py                    (usa as 3 URLs de exemplo abaixo)
    python diagnostico_produtos.py URL1 URL2 ...      (ou outras URLs de produto da Netshoes)

Do link so o CAMINHO do produto e usado: tudo depois do "?" e ignorado. Os codigos
de rastreio que vem nos links de outros grupos (ranEAID, ranSiteID, utm_...) nao
sao usados nem copiados.

O resultado tambem fica em diagnostico_produtos.txt.
"""
import re
import sys
from urllib.parse import urlparse

from clients.rakuten_client import RakutenClient
from core import rakuten_rules as rk

MID = "43984"  # Netshoes

DEFAULT_URLS = [
    "https://www.netshoes.com.br/p/camiseta-adidas-corrida-grafica-verde-FBA-83DX-060",
    "https://www.netshoes.com.br/p/camiseta-adidas-adi365-masculina-vermelho-FBA-83DT-016",
    "https://www.netshoes.com.br/p/camiseta-new-balance-athletics-graphic-masculina-marinho-39V-251V-012",
]

CODE = re.compile(r"-([A-Z0-9]{3}-[A-Z0-9]{4}-\d{3})$")
LINES = []


def out(text=""):
    print(text)
    LINES.append(str(text))


def parse_url(url):
    """Devolve (codigo_do_produto, palavras_do_nome) a partir do caminho da URL."""
    slug = urlparse(url.strip()).path.rstrip("/").split("/")[-1]
    match = CODE.search(slug)
    if not match:
        return None, []
    return match.group(1), [w for w in slug[: match.start()].split("-") if w]


def find(client, code, words):
    """Busca com cada vez menos palavras ate achar o codigo no sku ou no link."""
    for n in dict.fromkeys([len(words), 5, 4, 3]):
        term = " ".join(words[:n])
        for page in (1, 2):
            items = client.search_products(MID, term, page=page)
            hits = [p for p in items if p["sku"].startswith(code) or code in p["link"]]
            if hits:
                return term, hits
            if len(items) < 100:
                break
    return None, []


def verdict(product):
    """Por que este item nao entra (ou o que falta pra entrar) no 'melhor preco'."""
    reasons = []
    price = rk.effective_price(product)
    if product["price_cur"] != "BRL":
        reasons.append("moeda diferente de BRL")
    if not price or price < rk.BEST_PRICE_MIN_PRICE:
        reasons.append(f"preco abaixo do piso de R$ {rk.BEST_PRICE_MIN_PRICE:.0f}")
    if not rk.detect_brand(product["name"]):
        reasons.append("marca fora da lista")
    if not rk.detect_category(product["name"]):
        reasons.append("categoria fora da lista (tenis, camiseta, camisa, moletom...)")
    if not reasons:
        reasons.append(
            "passa nos filtros, mas so entra se estiver entre os mais baratos da sua "
            "marca/categoria (2 por categoria) e se a busca devolver o item"
        )
    return reasons


def main():
    urls = sys.argv[1:] or DEFAULT_URLS
    client = RakutenClient()

    for url in urls:
        code, words = parse_url(url)
        out("\n" + "=" * 64 + f"\n{urlparse(url).path.split('/')[-1]}\n" + "=" * 64)
        if not code:
            out("Nao achei o codigo do produto no final do link (ex.: ...-FBA-83DX-060).")
            continue
        out(f"Codigo do produto: {code} | palavras do nome: {' '.join(words)}")

        try:
            term, hits = find(client, code, words)
        except Exception as exc:
            out(f"[ERRO] {exc}")
            continue

        if not hits:
            out("NAO encontrei esse produto no feed (nem pelo sku nem pelo link).")
            out("Pode estar fora do feed, esgotado, ou a busca por nome nao o alcancou.")
            continue

        names = {p["name"] for p in hits}
        out(f"Achei no feed ({len(hits)} item(ns), {len(names)} nome(s)) buscando por: '{term}'")
        for p in hits[:3]:
            out(f"  {p['name'][:70]}")
            out(f"    price={p['price']} ({p['price_cur']}) | saleprice={p['sale']} | sku={p['sku']}")
            out(f"    link: {urlparse(p['link']).netloc} | imagem: {'sim' if p['image'] else 'nao'}")
        out("  Motivos pelos quais o bot nao o escolheu:")
        for reason in verdict(hits[0]):
            out(f"    - {reason}")

    out("\nLeitura: 'price' e o que o feed informa. O 'De R$' e o desconto que o outro grupo")
    out("mostra costumam vir da vitrine do site e de cupom/pix, e nao aparecem no feed.")

    with open("diagnostico_produtos.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(LINES))
    print("\nResultado salvo em diagnostico_produtos.txt")


if __name__ == "__main__":
    main()
