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
    if "productName" not in kw:  # cada oferta de teste tem um título próprio, como no mundo real
        base["productName"] = f"Perfume Natura Humor modelo {base['itemId']}"
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
        self.assertEqual(len([k for k in used if not k.startswith("n:")]), selector.BRAND_COUNT)

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

    def test_marcas_de_beleza_desligadas_e_totais(self):
        self.assertEqual(selector.ACTIVE_BRANDS, [])
        keys = [key for key, _ in selector.BLOCKS]
        self.assertEqual(keys, ["desconto", "vendas", "comissao", "casa"])
        brands = selector.BRAND_COUNT * len(selector.ACTIVE_BRANDS)
        general = sum(selector.GENERAL_COUNTS.values())
        self.assertEqual(brands + general, selector.SHOPEE_TARGET)
        self.assertEqual(selector.SHOPEE_TARGET, 22)
        self.assertEqual(selector.HOME_COUNT, 48)   # 20 + as 28 vagas das marcas
        pool = [offer(itemId=i, shopId=i % 5, priceDiscountRate=25 + i % 10, sales=100 + i) for i in range(1, 40)]
        chosen, _ = selector.pick_general(pool, "desconto", set(), set())
        self.assertEqual(len(chosen), selector.GENERAL_COUNTS["desconto"])


if __name__ == "__main__":
    unittest.main()


class HomeBlockTests(unittest.TestCase):
    def home_offer(self, i, term, **kw):
        base = dict(itemId=1000 + i, productName=f"{term} modelo {i}", _term=term,
                    priceDiscountRate=15, sales=500 - i, shopId=i)
        base.update(kw)
        return offer(**base)

    def pool(self):
        terms = ["organizador", "panela", "tapete", "cortina"]
        return [self.home_offer(n * 10 + k, t) for n, t in enumerate(terms) for k in range(10)]

    def test_casa_entra_nos_blocos_depois_das_listas_gerais(self):
        keys = [key for key, _ in selector.BLOCKS]
        self.assertEqual(keys[-1], "casa")
        self.assertEqual(dict(selector.BLOCKS)["casa"], "CASA")

    def test_escolhe_20_com_variedade_de_buscas(self):
        chosen, passed = selector.pick_home(self.pool(), set(), set(), count=20)
        self.assertEqual(len(chosen), 20)
        self.assertEqual(passed, 40)
        por_busca = {}
        for o in chosen:
            por_busca[o["_term"]] = por_busca.get(o["_term"], 0) + 1
        self.assertEqual(set(por_busca.values()), {5})   # 4 buscas, 5 de cada

    def test_nao_repete_bloqueados_nem_usados(self):
        blocked = {"1000", "1001"}
        used = {"1002"}
        chosen, _ = selector.pick_home(self.pool(), blocked, used)
        ids = {str(o["itemId"]) for o in chosen}
        self.assertFalse(ids & {"1000", "1001", "1002"})

    def test_filtros_de_qualidade_valem_na_casa(self):
        ruins = [
            self.home_offer(900, "panela", ratingStar="3.5"),            # nota baixa
            self.home_offer(901, "panela", priceDiscountRate=0),         # sem desconto
            self.home_offer(902, "panela", priceDiscountRate=80),        # desconto suspeito
            self.home_offer(903, "panela", productName="Panela similar"),  # nome bloqueado
        ]
        chosen, passed = selector.pick_home(ruins, set(), set())
        self.assertEqual((len(chosen), passed), (0, 0))

    def test_usa_o_que_tem_quando_faltam_produtos(self):
        chosen, _ = selector.pick_home(self.pool()[:7], set(), set())
        self.assertEqual(len(chosen), 7)


class RepeatedProductTests(unittest.TestCase):
    def test_chave_do_titulo_ignora_vendedor_pontuacao_e_acento(self):
        a = offer(itemId=1, productName="Organizador Multiuso Cozinha 5 Divisórias Gaveta Plástico - Preto")
        b = offer(itemId=2, productName="organizador multiuso, cozinha 5 divisorias gaveta plastico (azul)")
        self.assertEqual(selector.name_key(a), selector.name_key(b))
        self.assertTrue(selector.name_key(a).startswith("n:"))

    def test_titulo_curto_nao_gera_chave(self):
        self.assertEqual(selector.name_key(offer(itemId=1, productName="Panela")), "")

    def test_mesmo_produto_de_outro_vendedor_nao_entra_na_mesma_rodagem(self):
        pool = [
            offer(itemId=10, productName="Jogo de Panelas Antiaderente 5 Peças Vermelho", sales=900, shopId=1),
            offer(itemId=11, productName="Jogo de Panelas Antiaderente 5 Peças Vermelho", sales=800, shopId=2),
            offer(itemId=12, productName="Escorredor de Louças Inox Dobrável", sales=700, shopId=3),
        ]
        chosen, _ = selector.pick_general(pool, "vendas", set(), set())
        self.assertEqual(sorted(o["itemId"] for o in chosen), [10, 12])

    def test_bloqueia_pelo_titulo_de_um_envio_anterior(self):
        antigo = offer(itemId=99, productName="Escorredor de Louças Inox Dobrável Cozinha")
        blocked = {"99", selector.name_key(antigo)}
        novo = offer(itemId=500, productName="Escorredor de Louças Inox Dobrável Cozinha", shopId=7)
        outro = offer(itemId=501, productName="Tapete Antiderrapante Banheiro Microfibra", shopId=8)
        chosen, _ = selector.pick_general([novo, outro], "vendas", blocked, set())
        self.assertEqual([o["itemId"] for o in chosen], [501])

    def test_bloqueia_pelo_id(self):
        chosen, _ = selector.pick_general([offer(itemId=7)], "vendas", {"7"}, set())
        self.assertEqual(chosen, [])

    def test_nao_repete_entre_blocos_da_mesma_rodagem(self):
        used = set()
        pool = [offer(itemId=i, productName=f"Produto exclusivo numero {i} para casa", shopId=i) for i in range(1, 30)]
        a, _ = selector.pick_general(pool, "desconto", set(), used)
        b, _ = selector.pick_general(pool, "vendas", set(), used)
        self.assertFalse({o["itemId"] for o in a} & {o["itemId"] for o in b})


class SentMeanwhileTests(unittest.TestCase):
    def test_tira_o_que_outra_rodagem_enviou_no_meio_tempo(self):
        import sys, types
        for name, attrs in {"httpx": {"Response": object}}.items():
            sys.modules.setdefault(name, types.ModuleType(name)).__dict__.update(attrs)
        tn = sys.modules.setdefault("tenacity", types.ModuleType("tenacity"))
        tn.retry = lambda *a, **k: (lambda f: f); tn.stop_after_attempt = tn.wait_exponential = lambda *a, **k: None
        sb = sys.modules.setdefault("supabase", types.ModuleType("supabase"))
        sb.create_client = lambda *a, **k: None; sb.Client = object
        import main

        a = offer(itemId=1, productName="Escorredor de Louças Inox Dobrável")
        b = offer(itemId=2, productName="Tapete Antiderrapante Banheiro Microfibra")
        c = offer(itemId=3, productName="Escorredor de Louças Inox Dobrável")  # mesmo título de outro vendedor
        plan = [("casa", "CASA", [a, b, c])]
        original = main.get_recent_item_ids
        main.get_recent_item_ids = lambda days: {"2"} | {selector.name_key(a)}
        try:
            new_plan = main.drop_sent_meanwhile(plan)
        finally:
            main.get_recent_item_ids = original
        self.assertEqual(new_plan[0][2], [])  # a e c pelo título, b pelo ID
