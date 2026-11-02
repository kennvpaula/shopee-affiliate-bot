"""
Controle de ofertas já enviadas (Supabase, Postgres gratuito).

Tabela (veja sql/migracao_supabase.sql para a coluna nova `category`):
    sent_offers(item_id text primary key, product_name text,
                sent_at timestamptz default now(), category text)
"""
from datetime import datetime, timedelta, timezone

from supabase import Client, create_client

from config.settings import settings

_client: Client | None = None
_PAGE = 1000  # o Supabase devolve no máximo 1000 linhas por consulta


def get_client() -> Client:
    global _client
    if _client is None:
        _client = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
    return _client


def get_recent_item_ids(days: int) -> set[str]:
    """IDs das ofertas enviadas nos últimos `days` dias (essas não são escolhidas de novo)."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    client = get_client()
    ids: set[str] = set()
    start = 0
    while True:
        response = (
            client.table("sent_offers")
            .select("item_id")
            .gte("sent_at", since)
            .range(start, start + _PAGE - 1)
            .execute()
        )
        rows = response.data or []
        ids.update(str(row["item_id"]) for row in rows)
        if len(rows) < _PAGE:
            return ids
        start += _PAGE


def mark_as_sent(item_id: str, product_name: str, category: str | None = None) -> None:
    """Registra (ou renova) o envio. O sent_at é gravado de novo a cada envio."""
    client = get_client()
    row = {
        "item_id": str(item_id),
        "product_name": product_name,
        "sent_at": datetime.now(timezone.utc).isoformat(),
    }
    if category:
        try:
            client.table("sent_offers").upsert({**row, "category": category}).execute()
            return
        except Exception:
            pass  # coluna `category` ainda não existe: grava sem ela
    client.table("sent_offers").upsert(row).execute()
