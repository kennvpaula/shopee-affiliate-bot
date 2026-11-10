"""
Cliente da Rakuten Advertising (APIs de Product Search e Coupon Feed).

Token (confirmado em teste real): POST /token com
    Authorization: Bearer {token-key}   e   corpo  scope={SID}
devolve access_token (vale 3600 s). O bot pede um token novo no começo da rodagem
e renova sozinho se expirar no meio.

As respostas de produtos e cupons vêm em XML. Os leitores (parse_*) são funções
puras, testadas sem internet em tests/test_rakuten.py.
"""
import time
import xml.etree.ElementTree as ET

import httpx

from config.settings import settings
from core.rakuten_parse import parse_coupons, parse_products, sanitize_term

BASE = "https://api.linksynergy.com"
BRAZIL_NETWORK = 8  # rede do Brasil (BRL)
PAUSE = 0.7         # limite deles: 100 chamadas por minuto

# ----------------------------------------------------------------- cliente
class RakutenClient:
    def __init__(self):
        self.token_key = settings.RAKUTEN_TOKEN_KEY
        self.account_id = settings.RAKUTEN_ACCOUNT_ID
        self._token = None
        self._expires_at = 0.0

    def _fetch_token(self) -> None:
        headers = {
            "Authorization": f"Bearer {self.token_key}",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        last = ""
        # O guia mostra só "scope", mas o texto cita grant_type=password: tentamos os dois.
        for body in ({"scope": self.account_id}, {"grant_type": "password", "scope": self.account_id}):
            resp = httpx.post(f"{BASE}/token", headers=headers, data=body, timeout=40)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("access_token"):
                    self._token = data["access_token"]
                    self._expires_at = time.time() + int(data.get("expires_in", 3600)) - 120
                    return
            last = f"HTTP {resp.status_code}: {resp.text[:150]}"
        raise RuntimeError(f"Rakuten: não consegui gerar o token ({last})")

    def _get(self, path: str, params: dict | None = None) -> httpx.Response:
        for attempt in range(3):
            if not self._token or time.time() >= self._expires_at:
                self._fetch_token()
            resp = httpx.get(
                f"{BASE}{path}", params=params,
                headers={"Authorization": f"Bearer {self._token}"}, timeout=40,
            )
            if resp.status_code == 401 and attempt == 0:
                self._token = None  # token recusado: pede outro e tenta de novo
                continue
            if resp.status_code == 429:
                time.sleep(15)  # passou do limite por minuto
                continue
            if resp.status_code >= 400:
                raise RuntimeError(f"Rakuten HTTP {resp.status_code} em {path}: {resp.text[:200]}")
            time.sleep(PAUSE)
            return resp
        raise RuntimeError(f"Rakuten: sem resposta válida em {path} após várias tentativas")

    def search_products(self, mid: str, keyword: str, page: int = 1, per_page: int = 100) -> list[dict]:
        """Produtos de um anunciante que casam com o termo (até 100 por página)."""
        term = sanitize_term(keyword)
        params = {"mid": mid, "keyword": term, "max": per_page, "pagenumber": page}
        try:
            return parse_products(self._get("/productsearch/1.0", params).text)
        except ET.ParseError as exc:
            raise RuntimeError(f"Rakuten: resposta de produtos ilegível ({exc})")

    def list_coupons(self, network: int = BRAZIL_NETWORK, per_page: int = 100) -> list[dict]:
        try:
            xml_text = self._get("/coupon/1.0", {"network": network, "resultsperpage": per_page}).text
            return parse_coupons(xml_text)
        except ET.ParseError as exc:
            raise RuntimeError(f"Rakuten: resposta de cupons ilegível ({exc})")
