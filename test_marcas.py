"""
Teste SOMENTE LEITURA da Rakuten Advertising: descobre o que a sua conta enxerga.
Nao envia nada pro Telegram, nao grava no Supabase e nao mexe no bot.

Antes, no .env (na pasta do projeto), coloque UMA destas opcoes:

  A) Teste rapido (token temporario de 60 min, gerado na pagina "Applications"):
        RAKUTEN_ACCESS_TOKEN=...

  B) Como o bot vai funcionar (o script gera o token sozinho):
        RAKUTEN_TOKEN_KEY=...     (base64 de client_id:client_secret)
        RAKUTEN_ACCOUNT_ID=...    (o ID que a pagina Applications pede ao gerar o token)

Rode:
    python test_rakuten.py
    python test_rakuten.py --max-adv 15      (olha produtos de mais anunciantes)

O resultado tambem e salvo em resultado_rakuten.txt (nunca contem o token).
"""
import argparse
import os
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv

load_dotenv()

BASE = "https://api.linksynergy.com"
BRAZIL_NETWORK = 8  # segundo o guia de Partnerships: 8 = Brazil (BRL)
PAUSE = 0.7         # limite deles: 100 chamadas por minuto
LINES = []


def out(text=""):
    print(text)
    LINES.append(str(text))


def num(value):
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def domain(url):
    return urlparse(url or "").netloc or "(sem link)"


# ------------------------------------------------------------------ HTTP
def api_get(path, token, params=None):
    resp = httpx.get(
        BASE + path, params=params, headers={"Authorization": f"Bearer {token}"}, timeout=40
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"HTTP {resp.status_code} em {path}: {resp.text[:300]}")
    time.sleep(PAUSE)
    return resp


def get_token():
    direct = os.getenv("RAKUTEN_ACCESS_TOKEN", "").strip()
    if direct:
        out("[TOKEN] Usando RAKUTEN_ACCESS_TOKEN do .env (token temporario).")
        return direct

    key = os.getenv("RAKUTEN_TOKEN_KEY", "").strip()
    account = os.getenv("RAKUTEN_ACCOUNT_ID", "").strip()
    if not key or not account:
        raise SystemExit(
            "Faltam variaveis no .env: use RAKUTEN_ACCESS_TOKEN (teste rapido) "
            "ou RAKUTEN_TOKEN_KEY + RAKUTEN_ACCOUNT_ID."
        )

    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/x-www-form-urlencoded"}
    # O guia mostra o exemplo so com "scope", mas o texto cita grant_type=password: testamos os dois.
    for body in ({"scope": account}, {"grant_type": "password", "scope": account}):
        resp = httpx.post(BASE + "/token", headers=headers, data=body, timeout=40)
        if resp.status_code == 200 and "access_token" in resp.json():
            data = resp.json()
            variante = "COM grant_type=password" if "grant_type" in body else "so com scope"
            out(f"[TOKEN] OK ({variante}). Expira em {data.get('expires_in')} s. "
                f"Veio refresh_token: {'sim' if data.get('refresh_token') else 'nao'}.")
            return data["access_token"]
        out(f"[TOKEN] Tentativa ({', '.join(body)}) falhou: HTTP {resp.status_code} {resp.text[:200]}")
    raise SystemExit("Nao consegui gerar o token. Confira RAKUTEN_TOKEN_KEY e RAKUTEN_ACCOUNT_ID.")


# --------------------------------------------------------------- parsers
def parse_products(xml_text):
    root = ET.fromstring(xml_text)
    items = []
    for it in root.iter("item"):
        price_el, sale_el = it.find("price"), it.find("saleprice")
        items.append({
            "mid": it.findtext("mid"),
            "merchant": it.findtext("merchantname"),
            "sku": it.findtext("sku"),
            "name": (it.findtext("productname") or "").strip(),
            "price": num(price_el.text) if price_el is not None else None,
            "price_cur": price_el.get("currency") if price_el is not None else None,
            "sale": num(sale_el.text) if sale_el is not None else None,
            "sale_cur": sale_el.get("currency") if sale_el is not None else None,
            "link": it.findtext("linkurl"),
            "image": it.findtext("imageurl"),
        })
    first = next(root.iter("item"), None)
    tags = [child.tag for child in first] if first is not None else []
    return root.findtext("TotalMatches"), items, tags


def discount_pct(item):
    if item["price"] and item["sale"] and 0 < item["sale"] < item["price"]:
        return round((item["price"] - item["sale"]) / item["price"] * 100)
    return 0


def parse_date(value):
    try:
        return datetime.strptime((value or "").strip(), "%Y-%m-%dT%H:%MZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def parse_coupons(xml_text):
    root = ET.fromstring(xml_text)
    coupons = []
    for lk in root.iter("link"):
        coupons.append({
            "adv_id": (lk.findtext("advertiserid") or "").strip(),
            "adv_name": (lk.findtext("advertisername") or "").strip(),
            "desc": " ".join((lk.findtext("offerdescription") or "").split()),
            "start": parse_date(lk.findtext("offerstartdate")),
            "end": parse_date(lk.findtext("offerenddate")),
            "link": (lk.findtext("clickurl") or "").strip(),
            "code": (lk.findtext("couponcode") or "").strip(),
            "types": [t.text for t in lk.iter("promotiontype") if t.text],
        })
    first = next(root.iter("link"), None)
    tags = sorted({child.tag for child in first.iter() if child is not first}) if first is not None else []
    return root.findtext("TotalMatches"), coupons, tags


# ------------------------------------------------------------- consultas
def fetch_partnerships(token, network=None):
    items, page = [], 1
    while page <= 10:
        params = {"partner_status": "active", "advertiser_status": "active", "limit": 200, "page": page}
        if network:
            params["network"] = network
        batch = api_get("/v1/partnerships", token, params).json().get("partnerships", [])
        items += batch
        if len(batch) < 200:
            break
        page += 1
    return items


def fetch_advertisers_br(token):
    result, page = {}, 1
    while page <= 20:
        data = api_get("/v2/advertisers", token, {"network": BRAZIL_NETWORK, "limit": 100, "page": page}).json()
        batch = data.get("advertisers", [])
        for adv in batch:
            result[str(adv.get("id"))] = adv
        if len(batch) < 100:
            break
        page += 1
    return result


# ---------------------------------------------------------------- etapas
def step_partnerships(token):
    out("\n" + "=" * 64 + "\n1) ANUNCIANTES EM QUE VOCE ESTA APROVADO (Brasil, rede 8)\n" + "=" * 64)
    partners = fetch_partnerships(token, BRAZIL_NETWORK)
    out(f"{len(partners)} parceria(s) ativa(s) na rede do Brasil.")
    for p in partners:
        adv = p.get("advertiser", {})
        out(f"  mid {adv.get('id')} | {adv.get('name')} | {', '.join(adv.get('categories') or [])}")

    if not partners:
        out("\nNenhuma na rede 8. Vendo suas parcerias ativas em TODAS as redes (diagnostico):")
        every = fetch_partnerships(token)
        by_net = {}
        for p in every:
            by_net.setdefault(p.get("advertiser", {}).get("network"), []).append(p["advertiser"].get("name"))
        for net, names in sorted(by_net.items(), key=lambda kv: str(kv[0])):
            out(f"  rede {net}: {len(names)} anunciante(s), ex.: {', '.join(names[:5])}")
    return partners


def step_advertisers(token, partners):
    out("\n" + "=" * 64 + "\n2) RECURSOS DE CADA ANUNCIANTE (API Advertisers v2)\n" + "=" * 64)
    details = fetch_advertisers_br(token)
    out(f"{len(details)} anunciante(s) listados na rede do Brasil.")
    feed_ids = []
    for p in partners:
        adv_id = str(p["advertiser"]["id"])
        info = details.get(adv_id, {})
        feats = info.get("features", {})
        ships = (info.get("policies", {}).get("international_capabilities", {}) or {}).get("ships_to")
        out(f"  mid {adv_id} | {p['advertiser'].get('name')} | feed de produtos: {feats.get('product_feed')} | "
            f"deep links: {feats.get('deep_links')} | entrega em: {ships} | site: {info.get('url')}")
        if feats.get("product_feed") or not info:
            feed_ids.append(adv_id)
    out("\nATENCAO: a API nao informa as regras de divulgacao (grupos de mensagem, cupons etc.).")
    out("Leia os termos de cada programa no painel (Anunciantes) antes de liberar.")
    return feed_ids


def step_products(token, mids, partner_names, max_adv):
    out("\n" + "=" * 64 + "\n3) PRODUTOS (Product Search) POR ANUNCIANTE\n" + "=" * 64)
    if not mids:
        out("Nenhum anunciante com feed de produtos para testar.")
        return
    for mid in mids[:max_adv]:
        name = partner_names.get(mid, mid)
        out(f"\n--- {name} (mid {mid}) ---")
        try:
            xml_text = api_get("/productsearch/1.0", token, {"mid": mid, "language": "pt_BR", "max": 100}).text
            total, items, tags = parse_products(xml_text)
            if not items:
                xml_text = api_get("/productsearch/1.0", token, {"mid": mid, "max": 100}).text
                total, items, tags = parse_products(xml_text)
                out("(sem resultados com language=pt_BR; esta busca foi SEM filtro de idioma)")
        except Exception as exc:
            out(f"[ERRO] {exc}")
            continue

        if not items:
            out("Nenhum produto retornado.")
            continue

        currencies = sorted({i["price_cur"] or "?" for i in items} | {i["sale_cur"] or "?" for i in items if i["sale"]})
        promo = [i for i in items if discount_pct(i)]
        out(f"Total no feed: {total} | lidos: {len(items)} | moedas: {', '.join(currencies)} | "
            f"em promocao (saleprice menor que price): {len(promo)}")
        out(f"Campos de cada produto: {', '.join(tags)}")
        out(f"Link vem de: {domain(items[0]['link'])} | com imagem: {sum(1 for i in items if i['image'])}/{len(items)}")
        for i in sorted(promo, key=discount_pct, reverse=True)[:3]:
            out(f"  {discount_pct(i)}% OFF | {i['price_cur']} {i['price']} -> {i['sale']} | {i['name'][:60]} | sku {i['sku']}")


def step_coupons(token, partner_ids):
    out("\n" + "=" * 64 + "\n4) CUPONS (Coupon Feed, rede 8 = Brasil)\n" + "=" * 64)
    try:
        xml_text = api_get("/coupon/1.0", token, {"network": BRAZIL_NETWORK, "resultsperpage": 100}).text
        total, coupons, tags = parse_coupons(xml_text)
    except Exception as exc:
        out(f"[ERRO] {exc}")
        return

    now = datetime.now(timezone.utc)
    valid = [c for c in coupons if (not c["end"] or c["end"] >= now) and (not c["start"] or c["start"] <= now)]
    mine = [c for c in valid if c["adv_id"] in partner_ids]
    with_code = [c for c in coupons if c["code"]]
    out(f"Total: {total} | lidos: {len(coupons)} | validos agora: {len(valid)} | "
        f"validos de anunciantes aprovados: {len(mine)} | com campo de codigo: {len(with_code)}")
    out(f"Campos encontrados em cada cupom: {', '.join(tags)}")
    for c in sorted(mine, key=lambda c: c["end"] or now)[:10]:
        fim = c["end"].strftime("%d/%m") if c["end"] else "?"
        out(f"  {c['adv_name']} | ate {fim} | {c['types']} | codigo: {c['code'] or '(nao veio)'} | "
            f"{c['desc'][:90]} | link: {domain(c['link'])}")


def main():
    parser = argparse.ArgumentParser(description="Teste somente leitura da Rakuten")
    parser.add_argument("--max-adv", type=int, default=8, help="quantos anunciantes olhar nos produtos")
    args = parser.parse_args()

    token = get_token()
    partners = []
    try:
        partners = step_partnerships(token)
    except Exception as exc:
        out(f"[ERRO] Parcerias: {exc}")

    partner_ids = {str(p["advertiser"]["id"]) for p in partners}
    partner_names = {str(p["advertiser"]["id"]): p["advertiser"].get("name") for p in partners}

    feed_ids = []
    try:
        feed_ids = step_advertisers(token, partners)
    except Exception as exc:
        out(f"[ERRO] Anunciantes v2: {exc}")
        feed_ids = sorted(partner_ids)

    step_products(token, feed_ids, partner_names, args.max_adv)
    step_coupons(token, partner_ids)

    with open("resultado_rakuten.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(LINES))
    print("\nResultado salvo em resultado_rakuten.txt")


if __name__ == "__main__":
    main()
