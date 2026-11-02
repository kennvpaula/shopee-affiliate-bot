"""
Script de teste isolado — usa SÓ Telegram e Supabase, sem exigir
as credenciais da Shopee/WhatsApp (que ainda não estão prontas).

Rode com: python test_telegram_supabase.py
"""
import os
from dotenv import load_dotenv

load_dotenv()


def test_telegram():
    import httpx

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        print("[TELEGRAM] ❌ TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID não encontrado no .env")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": "✅ Teste de conexão do bot Mestre dos Achados! Se você está vendo isso, o Telegram está funcionando.",
    }

    with httpx.Client(timeout=15) as client:
        response = client.post(url, json=payload)

    if response.status_code == 200:
        print("[TELEGRAM] ✅ Mensagem enviada com sucesso! Confira o canal.")
        return True
    else:
        print(f"[TELEGRAM] ❌ Erro {response.status_code}: {response.text}")
        return False


def test_supabase():
    from supabase import create_client

    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")

    if not url or not key:
        print("[SUPABASE] ❌ SUPABASE_URL ou SUPABASE_KEY não encontrado no .env")
        return False

    try:
        client = create_client(url, key)
        # Testa inserindo e depois removendo um registro de teste
        test_id = "teste_conexao_999"
        client.table("sent_offers").upsert(
            {"item_id": test_id, "product_name": "Produto de teste"}
        ).execute()
        print("[SUPABASE] ✅ Inserção de teste bem-sucedida na tabela sent_offers!")

        client.table("sent_offers").delete().eq("item_id", test_id).execute()
        print("[SUPABASE] ✅ Limpeza do registro de teste concluída.")
        return True
    except Exception as e:
        print(f"[SUPABASE] ❌ Erro ao conectar: {e}")
        return False


if __name__ == "__main__":
    print("=== Testando Telegram ===")
    telegram_ok = test_telegram()

    print("\n=== Testando Supabase ===")
    supabase_ok = test_supabase()

    print("\n=== Resultado final ===")
    print(f"Telegram: {'OK ✅' if telegram_ok else 'FALHOU ❌'}")
    print(f"Supabase: {'OK ✅' if supabase_ok else 'FALHOU ❌'}")
