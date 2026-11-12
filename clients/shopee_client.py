"""
Cliente da Shopee Affiliate Open API (GraphQL), versão 2.

Autenticação (confirmada em teste real): header
    Authorization: SHA256 Credential={app_id},Timestamp={timestamp},Signature={signature}
com signature = sha256(app_id + timestamp + payload + secret), tudo concatenado
direto (sem separadores) e payload = corpo JSON exatamente como enviado.

Campos da query productOfferV2: portal do afiliado > Open API Document >
Get Product Offer List.
"""
import hashlib
import json
import time

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from config.settings import settings

_OFFER_QUERY = """
query ProductOffer($keyword: String, $limit: Int, $page: Int, $sortType: Int) {
  productOfferV2(keyword: $keyword, limit: $limit, page: $page, sortType: $sortType__SHOP_ARG__) {
    nodes {
      itemId
      productName
      priceMin
      priceMax
      priceDiscountRate
      commissionRate
      sales
      ratingStar
      imageUrl
      productLink
      offerLink
      shopId
      shopName
      shopType
    }
    pageInfo {
      page
      limit
      hasNextPage
    }
  }
}
"""


class ShopeeClient:
    # Valores de sortType confirmados na documentação oficial
    SORT_RELEVANCE = 1  # só vale junto com keyword
    SORT_ITEM_SOLD_DESC = 2
    SORT_PRICE_DESC = 3
    SORT_PRICE_ASC = 4
    SORT_COMMISSION_DESC = 5

    def __init__(self):
        self.app_id = settings.SHOPEE_APP_ID
        self.app_secret = settings.SHOPEE_APP_SECRET
        self.api_url = settings.SHOPEE_API_URL

    def _build_signature(self, payload_str: str, timestamp: int) -> str:
        # Concatenação DIRETA, sem separador: appId + timestamp + payload + secret
        base_string = f"{self.app_id}{timestamp}{payload_str}{self.app_secret}"
        return hashlib.sha256(base_string.encode("utf-8")).hexdigest()

    def _build_headers(self, payload_str: str) -> dict:
        timestamp = int(time.time())
        signature = self._build_signature(payload_str, timestamp)
        return {
            "Content-Type": "application/json",
            "Authorization": (
                f"SHA256 Credential={self.app_id},"
                f"Timestamp={timestamp},"
                f"Signature={signature}"
            ),
        }

    # O erro 10000 ("System Error") é do lado da Shopee e costuma passar sozinho: 4 tentativas, esperando 3, 6 e 12 s
    @retry(stop=stop_after_attempt(4), wait=wait_exponential(multiplier=3, max=15), reraise=True)
    def _execute(self, query: str, variables: dict | None = None) -> dict:
        body = {"query": query, "variables": variables or {}}
        # separators sem espaço: a assinatura é feita sobre essa string exata
        payload_str = json.dumps(body, separators=(",", ":"))
        headers = self._build_headers(payload_str)

        with httpx.Client(timeout=30) as client:
            response = client.post(self.api_url, content=payload_str, headers=headers)
            response.raise_for_status()
            data = response.json()

        if "errors" in data:
            raise RuntimeError(f"Erro retornado pela Shopee API: {data['errors']}")

        return data.get("data", {})

    def get_offers(
        self,
        keyword: str = "",
        limit: int = 20,
        page: int = 1,
        sort_type: int | None = None,
        shop_id: int | None = None,
    ) -> list[dict]:
        """
        Busca ofertas (query productOfferV2).

        sort_type: use as constantes SORT_* da classe.
        shop_id: restringe a uma loja (o id vai direto na query como número).
        """
        shop_arg = f", shopId: {int(shop_id)}" if shop_id else ""
        query = _OFFER_QUERY.replace("__SHOP_ARG__", shop_arg)

        variables: dict = {"limit": limit, "page": page}
        if keyword:
            variables["keyword"] = keyword
        if sort_type is not None:
            variables["sortType"] = sort_type

        data = self._execute(query, variables)
        return data.get("productOfferV2", {}).get("nodes", []) or []

    def generate_short_link(self, origin_url: str, sub_ids: list[str] | None = None) -> str:
        """
        Gera um link curto rastreável de afiliado a partir de uma URL de produto.
        NÃO TESTADO: confira o nome da mutation na doc "Get Short Link" antes de usar.
        """
        query = """
        mutation GenerateShortLink($input: ShortLinkInput!) {
          generateShortLink(input: $input) {
            shortLink
          }
        }
        """
        variables = {"input": {"originUrl": origin_url, "subIds": sub_ids or []}}
        data = self._execute(query, variables)
        return data.get("generateShortLink", {}).get("shortLink", origin_url)
