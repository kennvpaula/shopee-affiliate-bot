"""
Leitores puros (sem rede e sem credenciais) das respostas da Rakuten.
Usados pelo cliente (clients/rakuten_client.py) e testados em tests/test_rakuten.py.
"""
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

# Caracteres que a busca de produtos não aceita (segundo a documentação)
_FORBIDDEN = re.compile(r"[&=?{}\\()\[\];~|$!<>*%-]")


def sanitize_term(term: str) -> str:
    return " ".join(_FORBIDDEN.sub(" ", term).split())


def _num(value):
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- leitores
def parse_products(xml_text: str) -> list[dict]:
    root = ET.fromstring(xml_text)
    items = []
    for it in root.iter("item"):
        price_el, sale_el = it.find("price"), it.find("saleprice")
        items.append({
            "mid": (it.findtext("mid") or "").strip(),
            "merchant": (it.findtext("merchantname") or "").strip(),
            "sku": (it.findtext("sku") or "").strip(),
            "name": " ".join((it.findtext("productname") or "").split()),
            "price": _num(price_el.text) if price_el is not None else None,
            "price_cur": (price_el.get("currency") or "").upper() if price_el is not None else "",
            "sale": _num(sale_el.text) if sale_el is not None else None,
            "sale_cur": (sale_el.get("currency") or "").upper() if sale_el is not None else "",
            "link": (it.findtext("linkurl") or "").strip(),
            "image": (it.findtext("imageurl") or "").strip(),
        })
    return items


def _parse_date(value):
    try:
        return datetime.strptime((value or "").strip(), "%Y-%m-%dT%H:%MZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def parse_coupons(xml_text: str) -> list[dict]:
    root = ET.fromstring(xml_text)
    coupons = []
    for lk in root.iter("link"):
        coupons.append({
            "adv_id": (lk.findtext("advertiserid") or "").strip(),
            "adv_name": (lk.findtext("advertisername") or "").strip(),
            "desc": " ".join((lk.findtext("offerdescription") or "").split()),
            "start": _parse_date(lk.findtext("offerstartdate")),
            "end": _parse_date(lk.findtext("offerenddate")),
            "link": (lk.findtext("clickurl") or "").strip(),
            "code": (lk.findtext("couponcode") or "").strip(),
        })
    return coupons
