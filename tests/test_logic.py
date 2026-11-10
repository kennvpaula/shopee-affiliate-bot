"""
Testes das regras (sem internet, sem credenciais).
Rode na pasta do projeto:   python -m unittest tests.test_logic -v
"""
import unittest

from core import selector
from core.formatter import (
    clean_name,
    compute_original_price,
    format_post_caption,
    format_price_brl,
)

WA = "https://chat.whatsapp.com/abc"
TG = "https://t.me/omestredosachados"


def offer(**kw):
    base = {
        "itemId": 1, "productName": "Perfume Natura Humor", "priceMin": "100",
        "priceMax": "100", "priceDiscountRate": 20, "commissionRate": "0.03",
        "sales": 100, "ratingStar": "4.9", "imageUrl": "https://img/x.jpg",
        "offerLink": "https://shope.ee/x", "shopId": 1, "shopType": [2],
    }
    base.update(kw)
    return base


class FormatTests(unittest.TestCase):
    def test_preco_no_padrao_brasileiro(self):
        self.assertEqual(format_price_brl(111.9), "111,90")
        self.assertEqual(format_price_brl("24.9"), "24,90")
        self.assertEqual(format_price_brl(None), "?")

    def test_preco_de_calculado_pelo_desconto(self):
        self.assertEqual(compute_original_price(100.0, 20), 125.0)
        self.assertIsNone(compute_original_price(100.0, 0))

    def test_post_com_desconto(self):
        text = format_post_caption(offer(), WA, TG)
        self.assertIn("🏁 Perfume Natura Humor", text)
        self.assertIn("~De R$ 125,00~", text)
        self.assertIn("💵 *Por R$ 100,00*", text)
        self.assertIn(WA, text)
        self.assertIn(TG, text)
        self.assertNotIn("Cupom", text)

    def test_post_sem_desconto_nao_mostra_de(self):
        text = format_post_caption(offer(priceDiscountRate=0), WA, TG)
        self.assertNotIn("De R$", text)

    def test_cupom_aparece_so_quando_existe(self):
        text = format_post_caption(offer(coupon_code="NAT10"), WA, TG)
        self.assertIn("🎫 Cupom: NAT10", text)

    def test_nome_sem_simbolos_de_formatacao(self):
        self.assertEqual(clean_name("Kit *Promo* ~top~ Natura_Homem"), "Kit Promo top Natura Homem")


class SelectorTests(unittest.TestCase):
    def test_rejeita_inspiracao_e_desconto_suspeito(self):
        self.assertFalse(selector.is_good_offer(offer(productName="Body Splash Inspiração Natura"), 5))
        self.assertFalse(selector.is_good_offer(offer(priceDiscountRate=73), 5))
        self.assertTrue(selector.is_good_offer(offer(), 5))

    def test_vendedor_comum_exige_nota_e_vendas(self):
        self.assertFalse(selector.is_good_offer(offer(shopType=[], ratingStar="4.0"), 5))
        self.assertFalse(selector.is_good_offer(offer(shopType=[], sales=3), 5))
        self.assertTrue(selector.is_good_offer(offer(shopType=[]), 5))

    def test_marca_limita_por_loja_e_nao_repete(self):
        pool = [offer(itemId=i, shopId=i % 5, priceDiscountRate=50 - i) for i in range(1, 13)]
        used = set()
        chosen, passed = selector.pick_brand(pool, "natura", set(), used)
        self.assertEqual(len(chosen), selector.BRAND_COUNT)
        self.assertEqual(passed, 12)
        per_shop = {}
        for o in chosen:
            per_shop[o["shopId"]] = per_shop.get(o["shopId"], 0) + 1
        self.assertLessEqual(max(per_shop.values()), 2)
        self.assertEqual(len(used), selector.BRAND_COUNT)

        # segunda chamada (outro bloco) não pode repetir as já usadas
        chosen2, _ = selector.pick_brand(pool, "natura", set(), used)
        self.assertFalse({o["itemId"] for o in chosen} & {o["itemId"] for o in chosen2})

    def test_ofertas_recentes_sao_bloqueadas(self):
        pool = [offer(itemId=i) for i in range(1, 4)]
        chosen, _ = selector.pick_brand(pool, "natura", {"1", "2"}, set())
        self.assertEqual([o["itemId"] for o in chosen], [3])

    def test_marca_exige_nome_da_marca_ou_loja_da_marca(self):
        outra = offer(itemId=9, productName="Perfume Qualquer")
        da_loja = offer(itemId=10, productName="Kaiak Aventura", _from_brand_shop=True)
        chosen, _ = selector.pick_brand([outra, da_loja], "natura", set(), set())
        self.assertEqual([o["itemId"] for o in chosen], [10])

    def test_listas_gerais_ordenam_pelo_criterio(self):
        pool = [
            offer(itemId=1, sales=500, priceDiscountRate=20, commissionRate="0.03", shopId=1),
            offer(itemId=2, sales=900, priceDiscountRate=25, commissionRate="0.03", shopId=2),
            offer(itemId=3, sales=100, priceDiscountRate=40, commissionRate="0.10", shopId=3),
        ]
        vendas, _ = selector.pick_general(pool, "vendas", set(), set(), count=1)
        desconto, _ = selector.pick_general(pool, "desconto", set(), set(), count=1)
        comissao, _ = selector.pick_general(pool, "comissao", set(), set(), count=1)
        self.assertEqual(vendas[0]["itemId"], 2)
        self.assertEqual(desconto[0]["itemId"], 3)
        self.assertEqual(comissao[0]["itemId"], 3)

    def test_shopee_totaliza_50_por_rodagem(self):
        brands = selector.BRAND_COUNT * len(selector.BRANDS)
        general = sum(selector.GENERAL_COUNTS.values())
        self.assertEqual(brands + general, selector.SHOPEE_TARGET)
        self.assertEqual(selector.SHOPEE_TARGET, 50)
        pool = [offer(itemId=i, shopId=i % 5, priceDiscountRate=25 + i % 10, sales=100 + i) for i in range(1, 40)]
        chosen, _ = selector.pick_general(pool, "desconto", set(), set())
        self.assertEqual(len(chosen), selector.GENERAL_COUNTS["desconto"])


if __name__ == "__main__":
    unittest.main()
