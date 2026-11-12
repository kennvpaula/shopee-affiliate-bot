"""
Testes da Rakuten (sem internet, sem credenciais).
Rode na pasta do projeto:   python -m unittest tests.test_rakuten -v
"""
import unittest
from datetime import datetime, timezone

from core.rakuten_parse import parse_coupons, parse_products, sanitize_term
from core import rakuten_rules as rk
from core.formatter import format_post_caption

WA = "https://chat.whatsapp.com/abc"
TG = "https://t.me/omestredosachados"

PRODUCTS_XML = """<result><TotalMatches>3</TotalMatches><TotalPages>1</TotalPages><PageNumber>1</PageNumber>
<item><mid>54199</mid><merchantname>LojaNBA</merchantname><sku>A-1</sku><productname>Pochete NBA Celtics - Preto</productname>
<price currency="BRL">219.90</price><saleprice currency="BRL">71.99</saleprice>
<linkurl>https://click.linksynergy.com/x?id=1</linkurl><imageurl>https://img/a.jpg</imageurl></item>
<item><mid>54199</mid><merchantname>LojaNBA</merchantname><sku>B-1</sku><productname>Camiseta Infantil Time - Preto</productname>
<price currency="BRL">169.00</price><saleprice currency="BRL">85.49</saleprice>
<linkurl>https://click.linksynergy.com/x?id=2</linkurl><imageurl>https://img/b.jpg</imageurl></item>
<item><mid>54199</mid><merchantname>LojaNBA</merchantname><sku>B-2</sku><productname>Camiseta Infantil Time - Preto</productname>
<price currency="BRL">169.00</price><saleprice currency="BRL">85.49</saleprice>
<linkurl>https://click.linksynergy.com/x?id=3</linkurl><imageurl>https://img/b.jpg</imageurl></item>
</result>"""

COUPONS_XML = """<couponfeed><TotalMatches>3</TotalMatches>
<link type='TEXT'><offerdescription>Primeira Compra com 10% OFF( CUPOM)!</offerdescription><couponcode>PRIMEIRA10</couponcode>
<offerstartdate>2020-01-01T00:00Z</offerstartdate><offerenddate>2027-02-02T23:59Z</offerenddate>
<clickurl>https://click.linksynergy.com/c1</clickurl><advertiserid>43985</advertiserid><advertisername>Zattini WL</advertisername></link>
<link type='TEXT'><offerdescription>Ganhe 15% OFF na lista* (Cupom: TOPZAT)!</offerdescription>
<offerstartdate>2020-01-01T00:00Z</offerstartdate><offerenddate>2099-12-31T23:59Z</offerenddate>
<clickurl>https://click.linksynergy.com/c2</clickurl><advertiserid>43985</advertiserid><advertisername>Zattini WL</advertisername></link>
<link type='TEXT'><offerdescription>Cupom vencido</offerdescription>
<offerstartdate>2020-01-01T00:00Z</offerstartdate><offerenddate>2021-01-01T00:00Z</offerenddate>
<clickurl>https://click.linksynergy.com/c3</clickurl><advertiserid>43984</advertiserid><advertisername>Netshoes WL</advertisername></link>
</couponfeed>"""

NOW = datetime(2026, 11, 2, tzinfo=timezone.utc)


def product(**kw):
    base = {"mid": "43984", "merchant": "Netshoes", "sku": "S1", "name": "Tênis Nike Air", "price": 400.0,
            "price_cur": "BRL", "sale": 300.0, "sale_cur": "BRL", "link": "https://click/x", "image": "https://img/x.jpg"}
    base.update(kw)
    return base


NETSHOES = rk.ADVERTISERS["netshoes"][0]


class ParseTests(unittest.TestCase):
    def test_leitor_de_produtos(self):
        items = parse_products(PRODUCTS_XML)
        self.assertEqual(len(items), 3)
        self.assertEqual(items[0]["price"], 219.9)
        self.assertEqual(items[0]["sale"], 71.99)
        self.assertEqual(items[0]["price_cur"], "BRL")
        self.assertEqual(items[0]["mid"], "54199")

    def test_leitor_de_cupons(self):
        coupons = parse_coupons(COUPONS_XML)
        self.assertEqual(len(coupons), 3)
        self.assertEqual(coupons[0]["code"], "PRIMEIRA10")
        self.assertEqual(coupons[1]["code"], "")
        self.assertEqual(coupons[0]["end"].year, 2027)

    def test_termo_de_busca_sem_caracteres_proibidos(self):
        self.assertEqual(sanitize_term("under-armour (nike) & fila"), "under armour nike fila")
        self.assertEqual(sanitize_term("calvin klein"), "calvin klein")


def feed_item(name, price, mid="43984", sale=0.0, **kw):
    """Item como vem da Netshoes: saleprice 0 (o feed não informa promoção)."""
    return product(mid=mid, name=name, price=price, sale=sale, sale_cur="BRL", **kw)


ZATTINI = rk.ADVERTISERS["zattini"][0]
TEAMS = {a["name"]: a for a in rk.ADVERTISERS["times"]}


class ScoreTests(unittest.TestCase):
    def pick(self, items, advertiser=NETSHOES, total=30, blocked=None):
        return rk.pick_scored(items, advertiser, blocked or set(), set(), total)

    # ---- filtros
    def test_infantil_fica_de_fora_mas_feminino_entra(self):
        items = [
            feed_item("Tênis Nike Infantil Menino", 200.0),
            feed_item("Camiseta Adidas Kids", 80.0),
            feed_item("Tênis Nike Feminino Air", 250.0),
            feed_item("Tênis Nike Unissex Dunk", 280.0),
        ]
        offers, _ = self.pick(items)
        self.assertEqual(sorted(o["productName"] for o in offers),
                         ["Tênis Nike Feminino Air", "Tênis Nike Unissex Dunk"])

    def test_faixa_de_preco_por_categoria(self):
        items = [
            feed_item("Tênis Nike A", 90.0),       # abaixo de R$ 120
            feed_item("Tênis Nike B", 400.0),      # acima de R$ 350
            feed_item("Tênis Nike C", 199.0),      # ok
            feed_item("Camiseta New Balance Athletics Graphic Masculina", 55.55),   # ok (45 a 130)
            feed_item("Camiseta Adidas Premium", 150.0),                            # acima de R$ 130
        ]
        offers, _ = self.pick(items)
        self.assertEqual(sorted(o["productName"] for o in offers),
                         ["Camiseta New Balance Athletics Graphic Masculina", "Tênis Nike C"])

    def test_marca_conhecida_so_e_obrigatoria_nas_lojas_grandes(self):
        sem_marca = [feed_item("Tênis Esportivo Leve Masculino", 199.0)]
        self.assertEqual(self.pick(sem_marca)[0], [])
        time = TEAMS["LojaNBA"]
        no_time = [feed_item("Camiseta Time Blanks", 80.0, mid=time["mid"])]
        self.assertEqual(len(rk.pick_scored(no_time, time, set(), set(), 2)[0]), 1)

    def test_moeda_categoria_e_desconto_suspeito(self):
        items = [
            feed_item("Tênis Nike USD", 199.0, price_cur="USD"),
            feed_item("Meia Nike Cano Alto", 79.0),                    # categoria fora da lista
            feed_item("Tênis Nike Promo", 400.0, sale=150.0),          # 62% de desconto: entra
            feed_item("Tênis Nike Absurdo", 900.0, sale=200.0),        # 78% de desconto
            feed_item("Tênis Nike Bom", 249.0),
        ]
        names = [o["productName"] for o in self.pick(items)[0]]
        self.assertNotIn("Tênis Nike USD", names)
        self.assertNotIn("Meia Nike Cano Alto", names)
        self.assertNotIn("Tênis Nike Absurdo", names)
        self.assertIn("Tênis Nike Bom", names)

    # ---- nota
    def score(self, item, advertiser=NETSHOES, medians=None):
        return rk.score_product(item, advertiser, medians or {})

    def test_modelo_queridinho_ganha_pontos(self):
        lite = feed_item("Tênis Adidas Lite Racer 4.0", 199.0)
        outro = feed_item("Tênis Adidas Zeta", 199.0)
        self.assertGreater(self.score(lite), self.score(outro))

    def test_desconto_real_do_feed_ganha_pontos(self):
        com = feed_item("Tênis Nike Air", 300.0, sale=200.0)       # 33%
        sem = feed_item("Tênis Nike Air", 200.0)
        self.assertGreater(self.score(com), self.score(sem))
        self.assertEqual(rk.real_discount(feed_item("Tênis Nike Air", 300.0, sale=285.0)), 0)   # 5%: não conta

    def test_preco_bem_abaixo_dos_parecidos_ganha_pontos(self):
        group = [feed_item(f"Tênis Nike M{i}", 300.0 + i) for i in range(6)]
        medians = rk.group_medians(group)
        barato = feed_item("Tênis Nike Barato", 200.0)
        normal = feed_item("Tênis Nike Normal", 301.0)
        self.assertGreater(self.score(barato, medians=medians), self.score(normal, medians=medians))

    # ---- seleção
    def test_trinta_por_loja_com_70_por_cento_de_tenis_e_variedade_de_marcas(self):
        items = []
        for brand in ("Nike", "Adidas", "Puma", "Asics", "Mizuno", "Olympikus"):
            items += [feed_item(f"Tênis {brand} Modelo {i}", 150.0 + i * 8) for i in range(8)]
        for cat in ("Camiseta", "Moletom", "Jaqueta", "Mochila", "Bermuda", "Legging", "Camisa", "Chuteira"):
            items += [feed_item(f"{cat} Nike Linha {i}", 70.0 + i * 5) for i in range(3)]
        offers, _ = self.pick(items, total=30)
        self.assertEqual(len(offers), 30)
        sneakers = [o for o in offers if rk.detect_category(o["productName"]) == "tenis"]
        self.assertGreaterEqual(len(sneakers), 21)                      # foco em tênis (70% ou mais)
        self.assertEqual(len({rk.detect_brand(o["productName"]) for o in sneakers}), 6)

    def test_zattini_usa_a_mesma_regra(self):
        items = [feed_item(f"Tênis Mizuno Modelo {i}", 150.0 + i, mid="43985") for i in range(40)]
        offers, _ = self.pick(items, advertiser=ZATTINI, total=30)
        self.assertEqual(len(offers), 30)

    def test_um_post_por_produto_e_nao_por_tamanho(self):
        items = [feed_item("Tênis Nike A", 250.0), feed_item("Tênis Nike A", 250.0, sku="X2"),
                 feed_item("Tênis Nike B", 260.0)]
        offers, passed = self.pick(items, total=5)
        self.assertEqual(sorted(o["productName"] for o in offers), ["Tênis Nike A", "Tênis Nike B"])
        self.assertEqual(passed, 2)

    def test_lojas_de_time_2_por_loja_com_categorias_diferentes_e_cruzeiro_5(self):
        for name, quantity in (("Santos Store", 2), ("Cruzeiro Store", 5)):
            adv = TEAMS[name]
            items = []
            for cat in ("Camisa", "Moletom", "Jaqueta", "Bermuda", "Mochila", "Camiseta"):
                items += [feed_item(f"{cat} {name} {i}", 300.0, sale=150.0 + i, mid=adv["mid"]) for i in range(3)]
            offers, _ = rk.pick_scored(items, adv, set(), set(), adv["total"])
            self.assertEqual(len(offers), quantity)
            cats = {rk.detect_category(o["productName"]) for o in offers}
            self.assertEqual(len(cats), quantity)       # categorias diferentes
        self.assertEqual(TEAMS["Cruzeiro Store"]["total"], 5)
        self.assertTrue(all(a["total"] == 2 for n, a in TEAMS.items() if n != "Cruzeiro Store"))

    def test_time_com_desconto_mostra_de_e_por(self):
        adv = TEAMS["Shop Timao"]
        item = feed_item("Camiseta Corinthians Quebrada Feminina", 179.0, sale=130.0, mid=adv["mid"])
        offers, _ = rk.pick_scored([item], adv, set(), set(), 2)
        text = format_post_caption(offers[0], WA, TG)
        self.assertIn("~De R$ 179,00~", text)
        self.assertIn("💵 *Por R$ 130,00*", text)

    def test_cooldown_total_restante_e_total_zero(self):
        items = [feed_item(f"Tênis Nike Modelo {i}", 200.0 + i) for i in range(5)]
        blocked = {rk.product_key("43984", "Tênis Nike Modelo 0")}
        offers, _ = self.pick(items, total=3, blocked=blocked)
        self.assertEqual(len(offers), 3)
        self.assertNotIn("Tênis Nike Modelo 0", [o["productName"] for o in offers])
        self.assertEqual(self.pick(items, total=0), ([], 0))

    def test_exemplos_do_outro_grupo_entram(self):
        # Camisetas dos prints que você mandou, com o preço do feed
        items = [
            feed_item("Camiseta Adidas Corrida Gráfica - Unissex", 66.65),
            feed_item("Camiseta Adidas Adi365 Masculina - Masculino", 77.77),
            feed_item("Camiseta New Balance Athletics Graphic Masculina - Masculino", 55.55),
        ]
        offers, _ = self.pick(items, total=30)
        self.assertEqual(len(offers), 3)

    def test_post_sem_desconto_nao_promete_desconto(self):
        offers, _ = self.pick([feed_item("Tênis Nike Bom", 249.0)], total=5)
        text = format_post_caption(offers[0], WA, TG)
        self.assertIn("💵 *Por R$ 249,00*", text)
        self.assertNotIn("De R$", text)
        self.assertIn("Link ↘️", text)
        self.assertNotIn("Link com desconto", text)


class FavoriteBrandTests(unittest.TestCase):
    BRANDS = ("Nike", "Adidas", "Puma", "Asics", "Mizuno", "Olympikus", "Fila", "Vans")

    def big_pool(self):
        items = []
        for brand in self.BRANDS:
            items += [feed_item(f"Tênis {brand} Modelo {i}", 150.0 + i * 6) for i in range(12)]
            items += [feed_item(f"Camiseta {brand} Linha {i}", 60.0 + i * 4) for i in range(6)]
        return items

    @staticmethod
    def count(offers, brand):
        return sum(1 for o in offers if rk.detect_brand(o["productName"]) == brand)

    def test_nike_e_adidas_tem_cota_minima_com_foco_em_tenis(self):
        offers, _ = rk.pick_scored(self.big_pool(), NETSHOES, set(), set(), NETSHOES["total"])
        self.assertEqual(len(offers), NETSHOES["total"])
        for brand in ("nike", "adidas"):
            self.assertGreaterEqual(self.count(offers, brand), rk.FAVORITE_BRANDS[brand])
            mine = [o for o in offers if rk.detect_brand(o["productName"]) == brand]
            sneakers = [o for o in mine if rk.detect_category(o["productName"]) == "tenis"]
            self.assertGreaterEqual(len(sneakers) / len(mine), 0.6)   # a cota também é de tênis
        # as outras marcas continuam aparecendo
        self.assertGreaterEqual(len({rk.detect_brand(o["productName"]) for o in offers}), 6)

    def test_campanha_conta_para_a_cota_da_marca(self):
        camp = campaign("Adidas Campus")
        pre = rk.pick_campaign([feed_item(f"Tênis Adidas Campus Cor {i}", 400.0 + i) for i in range(5)],
                               NETSHOES, camp, set(), set())
        self.assertEqual(len(pre), 5)
        offers, _ = rk.pick_scored(self.big_pool(), NETSHOES, set(), {o["itemId"] for o in pre}, 25, preselected=pre)
        self.assertEqual(len(offers), 25)
        self.assertGreaterEqual(self.count(offers, "adidas") + self.count(pre, "adidas"), rk.FAVORITE_BRANDS["adidas"])

    def test_sem_produtos_da_marca_o_total_fecha_com_as_outras(self):
        items = [i for i in self.big_pool() if rk.detect_brand(i["name"]) not in ("nike", "adidas")]
        offers, _ = rk.pick_scored(items, NETSHOES, set(), set(), 30)
        self.assertEqual(len(offers), 30)
        self.assertEqual(self.count(offers, "nike") + self.count(offers, "adidas"), 0)

    def test_lojas_de_time_nao_tem_cota_de_marca(self):
        self.assertTrue(all(not a["favorites"] for a in rk.ADVERTISERS["times"]))
        self.assertEqual(NETSHOES["favorites"], {"nike": 12, "adidas": 12})
        self.assertEqual(ZATTINI["favorites"], {"nike": 12, "adidas": 12})
        self.assertEqual((NETSHOES["total"], ZATTINI["total"]), (40, 40))

    def test_busca_traz_mais_roupa_de_nike_e_adidas(self):
        for term in ("camiseta nike", "moletom adidas", "jaqueta nike", "mochila adidas"):
            self.assertIn(term, rk.BIG_TERMS)

    def test_busca_traz_modelos_favoritos_de_nike_e_adidas(self):
        for term in ("nike air max", "nike pegasus", "adidas samba", "adidas campus"):
            self.assertIn(term, rk.BIG_TERMS)

    def test_lojas_de_time_nao_buscam_modelos_de_marca(self):
        for advertiser in rk.ADVERTISERS["times"]:
            self.assertNotIn("nike air max", advertiser["terms"])


class CaptionTests(unittest.TestCase):
    def test_post_de_produto_usa_preco_de_real(self):
        offer = rk.to_offer("k", product(price=219.9, sale=71.99), "Netshoes")
        text = format_post_caption(offer, WA, TG)
        self.assertIn("~De R$ 219,90~", text)  # real, não calculado pelo %
        self.assertIn("💵 *Por R$ 71,99*", text)
        self.assertIn("https://click/x", text)
        self.assertIn(TG, text)


def real_coupon(adv_id, desc, code="", end=None):
    return {"adv_id": adv_id, "adv_name": "X", "desc": desc, "code": code, "link": "https://click/c",
            "start": datetime(2020, 1, 1, tzinfo=timezone.utc),
            "end": end or datetime(2027, 12, 31, tzinfo=timezone.utc)}


# Os 7 cupons reais do feed da conta (Zattini = 43985, Netshoes = 43984)
REAL = [
    real_coupon("43985", "Ganhe 15% OFF na lista em todo o site* (Cupom: TOPZAT)!"),
    real_coupon("43985", "Primeira Compra com 10% OFF( CUPOM)!", code="PRIMEIRA10"),
    real_coupon("43985", "Compre 1 item da lista e leve um mimo por R$9,99!"),
    real_coupon("43985", "Acima de R$ 239, LEVE 1 carteira por R$ 1!"),
    real_coupon("43984", "Cupom de 10% OFF na primeira compra (Cupom) - Validade: Indeterminada!", code="BEMVINDO10"),
    real_coupon("43984", "Under Armor Com Até 30% Off!"),
    real_coupon("43984", "5% Em Itens Asics!"),
]


class CouponToProductTests(unittest.TestCase):
    def usable(self):
        return rk.parse_coupons_for_products(REAL, now=NOW)

    def test_so_o_que_da_para_ligar_a_produto(self):
        self.assertEqual(len(self.usable()), 5)   # "item da lista" e "acima de R$ 239" ficam de fora

    def test_codigo_vem_do_campo_ou_do_texto(self):
        codes = {c["code"] for c in self.usable()}
        self.assertEqual(codes, {"TOPZAT", "PRIMEIRA10", "BEMVINDO10", ""})

    def test_marca_com_grafia_da_rakuten(self):
        brands = {c["brand"] for c in self.usable()}
        self.assertEqual(brands, {None, "under armour", "asics"})   # "Under Armor" vira under armour

    def test_cupom_vencido_ou_futuro_nao_entra(self):
        old = real_coupon("43984", "Cupom de 10% OFF (Cupom: VELHO10)", end=datetime(2021, 1, 1, tzinfo=timezone.utc))
        self.assertEqual(rk.parse_coupons_for_products([old], now=NOW), [])

    def test_zattini_recebe_o_melhor_cupom_da_loja(self):
        offer = {"_mid": "43985", "productName": "Tênis Mizuno Wave Titan 3"}
        lines = rk.coupon_lines_for(offer, self.usable())
        self.assertEqual(lines, ["🎫 Cupom TOPZAT: 15% OFF (*confira as condições)"])

    def test_netshoes_loja_mais_marca_do_produto(self):
        asics = {"_mid": "43984", "productName": "Tênis Asics Gel Nimbus"}
        self.assertEqual(rk.coupon_lines_for(asics, self.usable()), [
            "🎫 Cupom BEMVINDO10: 10% OFF (1ª compra)",
            "🏷️ Promoção Asics: 5% OFF",
        ])
        under = {"_mid": "43984", "productName": "Camiseta Under Armour Tech"}
        self.assertEqual(rk.coupon_lines_for(under, self.usable())[1], "🏷️ Promoção Under Armour: até 30% OFF")

    def test_produto_de_outra_marca_ou_loja_nao_recebe_cupom_da_marca(self):
        nike = {"_mid": "43984", "productName": "Tênis Nike Air"}
        self.assertEqual(rk.coupon_lines_for(nike, self.usable()), ["🎫 Cupom BEMVINDO10: 10% OFF (1ª compra)"])
        time = {"_mid": "54199", "productName": "Camiseta Time"}
        self.assertEqual(rk.coupon_lines_for(time, self.usable()), [])

    def test_attach_marca_so_as_ofertas_aplicaveis(self):
        offers = [{"_mid": "43985", "productName": "Tênis Puma"}, {"_mid": "54199", "productName": "Camisa Time"}]
        self.assertEqual(rk.attach_coupons(offers, self.usable()), 1)
        self.assertNotIn("coupon_lines", offers[1])

    def test_post_traz_o_cupom_entre_o_preco_e_o_link(self):
        offer = {"_mid": "43985", "productName": "Tênis Mizuno Wave Titan 3", "priceMin": 249.99,
                 "offerLink": "https://click/x", "priceDiscountRate": 0}
        rk.attach_coupons([offer], self.usable())
        text = format_post_caption(offer, WA, TG)
        self.assertLess(text.index("💵 *Por R$ 249,99*"), text.index("🎫 Cupom TOPZAT"))
        self.assertLess(text.index("🎫 Cupom TOPZAT"), text.index("https://click/x"))


def campaign(name):
    return next(c for c in rk.CAMPAIGNS if c["name"] == name)


class CampaignTests(unittest.TestCase):
    def test_janelas_de_data(self):
        def active(day, hour):   # hora em UTC
            now = datetime(2026, 11, day, hour, 0, tzinfo=timezone.utc)
            return [c["name"] for c in rk.active_campaigns("43984", now)]
        self.assertEqual(active(4, 15), ["Asics GT-2160"])        # 04/11 de manhã em Brasília
        self.assertEqual(active(5, 2), ["Asics GT-2160"])         # 04/11 às 23h em Brasília: ainda vale
        self.assertEqual(active(5, 3), ["Adidas Campus"])         # 05/11 00h em Brasília: troca
        self.assertEqual(active(8, 12), ["Adidas Superstar"])
        self.assertEqual(active(10, 12), ["New Balance 1000"])
        self.assertEqual(active(12, 12), ["New Balance 530"])
        self.assertEqual(active(13, 3), [])                       # acabou
        self.assertEqual(rk.active_campaigns("54199", datetime(2026, 11, 4, 12, tzinfo=timezone.utc)), [])  # outra loja

    def test_reconhece_o_modelo_pelo_nome(self):
        gt = campaign("Asics GT-2160")
        self.assertTrue(rk.matches_campaign("Tênis Asics GT-2160 Masculino - Preto", gt))
        self.assertTrue(rk.matches_campaign("Tenis Asics Gt2160 Feminino", gt))
        self.assertFalse(rk.matches_campaign("Tênis Asics Gel Nimbus 25", gt))
        self.assertFalse(rk.matches_campaign("Tênis Mizuno GT-2160", gt))          # falta a marca
        nb = campaign("New Balance 530")
        self.assertTrue(rk.matches_campaign("Tênis New Balance 530 Unissex", nb))
        self.assertFalse(rk.matches_campaign("Tênis New Balance 5300 Masculino", nb))   # número inteiro
        self.assertTrue(rk.matches_campaign("Tênis Campus Adidas Originals", campaign("Adidas Campus")))

    def test_pick_campaign_cores_diferentes_do_mais_barato_ao_mais_caro(self):
        camp = campaign("Adidas Superstar")
        items = [
            feed_item("Tênis Adidas Superstar - Branco", 599.0),
            feed_item("Tênis Adidas Superstar - Preto", 549.0),
            feed_item("Tênis Adidas Superstar - Preto", 549.0, sku="X2"),   # mesmo modelo em outro tamanho
            feed_item("Tênis Adidas Samba - Preto", 400.0),                  # outro modelo
        ]
        used = set()
        offers = rk.pick_campaign(items, NETSHOES, camp, set(), used)
        self.assertEqual([o["productName"] for o in offers],
                         ["Tênis Adidas Superstar - Preto", "Tênis Adidas Superstar - Branco"])
        self.assertTrue(all(o["_campaign"] == "Adidas Superstar" for o in offers))
        self.assertEqual(len(used), 2)

    def test_pick_campaign_respeita_limite_e_cooldown(self):
        camp = campaign("Adidas Campus")
        items = [feed_item(f"Tênis Adidas Campus Cor {i}", 400.0 + i) for i in range(10)]
        blocked = {rk.product_key("43984", "Tênis Adidas Campus Cor 0")}
        offers = rk.pick_campaign(items, NETSHOES, camp, blocked, set())
        self.assertEqual(len(offers), rk.CAMPAIGN_LIMIT)
        self.assertNotIn("Tênis Adidas Campus Cor 0", [o["productName"] for o in offers])

    def test_post_da_campanha_nao_mostra_comissao(self):
        camp = campaign("Adidas Campus")
        offers = rk.pick_campaign([feed_item("Tênis Adidas Campus 00s", 499.0)], NETSHOES, camp, set(), set())
        text = format_post_caption(offers[0], WA, TG)
        self.assertNotIn("comiss", text.lower())
        self.assertNotIn("15%", text)
        self.assertIn("💵 *Por R$ 499,00*", text)


if __name__ == "__main__":
    unittest.main()
