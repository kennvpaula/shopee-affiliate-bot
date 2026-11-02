"""
Carrega e valida as variáveis de ambiente usadas em todo o projeto.
Em produção (GitHub Actions) elas vêm dos "Secrets" do repositório;
localmente vêm do arquivo .env (nunca commitado).

Obs.: no GitHub, um Secret que não existe chega como texto vazio (""), e não
como "ausente". Por isso os valores opcionais usam _get(), que trata vazio
como "usar o padrão".
"""
import os

from dotenv import load_dotenv

load_dotenv()


def _get(name: str, default: str = "") -> str:
    value = (os.getenv(name) or "").strip()
    return value or default


def _get_required(name: str) -> str:
    value = _get(name)
    if not value:
        raise RuntimeError(
            f"Variável de ambiente obrigatória ausente: {name}. "
            f"Confira seu .env ou os Secrets do GitHub Actions."
        )
    return value


def _get_bool(name: str, default: bool) -> bool:
    value = _get(name)
    if not value:
        return default
    return value.lower() in ("1", "true", "yes", "sim", "on")


def _get_int(name: str, default: int) -> int:
    try:
        return int(_get(name, str(default)))
    except ValueError:
        return default


def _get_float(name: str, default: float) -> float:
    try:
        return float(_get(name, str(default)).replace(",", "."))
    except ValueError:
        return default


class Settings:
    # ---- Shopee (obrigatório) ----
    SHOPEE_APP_ID = _get_required("SHOPEE_APP_ID")
    SHOPEE_APP_SECRET = _get_required("SHOPEE_APP_SECRET")
    SHOPEE_API_URL = _get(
        "SHOPEE_API_URL", "https://open-api.affiliate.shopee.com.br/graphql"
    )

    # ---- Telegram (obrigatório) ----
    TELEGRAM_BOT_TOKEN = _get_required("TELEGRAM_BOT_TOKEN")
    TELEGRAM_CHAT_ID = _get_required("TELEGRAM_CHAT_ID")
    TELEGRAM_SILENT = _get_bool("TELEGRAM_SILENT", True)  # posts sem notificação sonora
    SEND_DELAY_SECONDS = _get_float("SEND_DELAY_SECONDS", 3.5)  # pausa entre posts

    # ---- Supabase (obrigatório) ----
    SUPABASE_URL = _get_required("SUPABASE_URL")
    SUPABASE_KEY = _get_required("SUPABASE_KEY")

    # ---- Links que aparecem no fim de cada post ----
    WHATSAPP_GROUP_LINK = _get(
        "WHATSAPP_GROUP_LINK",
        "https://chat.whatsapp.com/Ls5NSq99JcRLMl1MiDNwEN?s=cl&p=i&mlu=4&ilr=4",
    )
    TELEGRAM_GROUP_LINK = _get("TELEGRAM_GROUP_LINK", "https://t.me/omestredosachados")

    # ---- Regras ----
    # Uma oferta enviada não volta a ser escolhida por este número de dias
    COOLDOWN_DAYS = _get_int("COOLDOWN_DAYS", 3)

    # ---- WhatsApp Cloud API (DESLIGADO por padrão: evita custo no cartão) ----
    # Para religar: WHATSAPP_ENABLED=true e preencher as variáveis abaixo.
    WHATSAPP_ENABLED = _get_bool("WHATSAPP_ENABLED", False)
    WHATSAPP_TOKEN = _get("WHATSAPP_TOKEN")
    WHATSAPP_PHONE_NUMBER_ID = _get("WHATSAPP_PHONE_NUMBER_ID")
    WHATSAPP_API_VERSION = _get("WHATSAPP_API_VERSION", "v20.0")
    WHATSAPP_TO_NUMBERS = [
        n.strip() for n in _get("WHATSAPP_TO_NUMBERS").split(",") if n.strip()
    ]
    WHATSAPP_TEMPLATE_NAME = _get("WHATSAPP_TEMPLATE_NAME")
    WHATSAPP_TEMPLATE_LANGUAGE = _get("WHATSAPP_TEMPLATE_LANGUAGE", "pt_BR")


settings = Settings()
