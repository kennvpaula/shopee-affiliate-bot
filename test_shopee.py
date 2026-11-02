"""
Script de teste isolado — testa SÓ a conexão com a Shopee Affiliate API,
sem depender de Telegram, WhatsApp ou Supabase.

Rode com: python test_shopee.py
"""
import os
from dotenv import load_dotenv

load_dotenv()


def test_shopee():
    from clients.shopee_client import ShopeeClient

    app_id = os.getenv("SHOPEE_APP_ID")
    app_secret = os.getenv("SHOPEE_APP_SECRET")

    if not app_id or not app_secret:
        print("[SHOPEE] ❌ SHOPEE_APP_ID ou SHOPEE_APP_SECRET não encontrado no .env")
        return False

    try:
        client = ShopeeClient()
        print("[SHOPEE] Buscando ofertas de teste (limit=3)...")
        offers = client.get_offers(limit=3)

        if not offers:
            print(
                "[SHOPEE] ⚠️  A API respondeu, mas não retornou nenhuma oferta. "
                "Isso pode ser normal (sem ofertas disponíveis agora) ou indicar que "
                "o nome do campo da query (productOfferV2) mudou — confira a doc oficial."
            )
            return True

        print(f"[SHOPEE] ✅ {len(offers)} oferta(s) recebida(s) com sucesso!\n")
        for i, offer in enumerate(offers, start=1):
            print(f"--- Oferta {i} ---")
            print(f"  Nome: {offer.get('productName')}")
            print(f"  Preço: R$ {offer.get('price')}")
            print(f"  Comissão: {offer.get('commissionRate')}%")
            print(f"  Link: {offer.get('offerLink') or offer.get('productLink')}")
            print(f"  Imagem: {offer.get('imageUrl')}")
            print()

        return True

    except Exception as e:
        # Se for um RetryError do tenacity, a exceção real está escondida dentro dele
        real_error = e
        if type(e).__name__ == "RetryError":
            try:
                real_error = e.last_attempt.exception()
            except Exception:
                pass

        print(f"[SHOPEE] ❌ Erro ao conectar: {real_error}")
        print(f"[SHOPEE] (tipo do erro: {type(real_error).__name__})")
        print(
            "\nDicas de depuração:\n"
            "1. Confira se SHOPEE_APP_ID e SHOPEE_APP_SECRET estão corretos no .env\n"
            "2. Confira na doc oficial (logada) se o nome do campo da query mudou\n"
            "   (ex: productOfferV2 pode ter virado outro nome)\n"
            "3. Confira se sua conta de afiliado está com status aprovado/ativo"
        )
        return False


if __name__ == "__main__":
    print("=== Testando Shopee Affiliate API ===\n")
    ok = test_shopee()
    print("\n=== Resultado final ===")
    print(f"Shopee: {'OK ✅' if ok else 'FALHOU ❌'}")
