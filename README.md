# Mestre dos Achados — bot de ofertas Shopee -> Telegram

Busca ofertas na Shopee Affiliate API e posta no canal do Telegram, com a foto do
produto em cima e o texto no modelo do WhatsApp (você copia e cola no grupo).
O envio pelo WhatsApp Cloud API fica **desligado** (evita custo no cartão).

## O que cada rodagem faz

| Bloco | Quantas | Como escolhe |
|---|---|---|
| Boticário, Natura, Wepink, Eudora | até 5 cada | maior desconto, depois maior comissão |
| Top desconto | 3 | maiores descontos reais do catálogo |
| Top vendas | 3 | mais vendidos, com desconto mínimo |
| Top comissão | 3 | maiores comissões |

Filtros (ajustáveis no topo de `core/selector.py`): nota mínima, vendas mínimas de
vendedor comum, desconto acima de 60% é descartado como suspeito, nomes com
"inspiração", "similar", "compatível" etc. ficam de fora, e no máximo 2 ofertas da
mesma loja por bloco. Uma oferta enviada não volta por `COOLDOWN_DAYS` dias (padrão 3).

Se um bloco não tiver ofertas boas e novas, o bot posta as que achar e avisa no log.

## Comandos

```
python main.py                        # rodagem completa
python main.py --dry-run              # só MOSTRA os posts (não envia nem grava)
python main.py --only natura,vendas   # só alguns blocos
python -m unittest tests.test_logic -v   # testes das regras
python test_marcas.py                 # lista lojas/vendedores por marca (só leitura)
```

Blocos: `boticario, natura, wepink, eudora, desconto, vendas, comissao`.

## Configuração

1. `cp .env.example .env` e preencha Shopee, Telegram e Supabase.
2. No Supabase (SQL Editor), rode uma vez `sql/migracao_supabase.sql`.
3. Teste com `python main.py --dry-run --only natura` e depois `python main.py --only natura`.

## Agendamento (GitHub Actions)

`.github/workflows/scheduler.yml` roda 7 vezes por dia (5h, 7h30, 10h, 12h, 15h, 17h
e 19h de Brasília; cada rodagem começa ~10 min antes por causa dos atrasos do GitHub).

1. Crie um repositório (privado) e suba o código (o `.env` nunca vai junto).
2. Settings > Secrets and variables > Actions: cadastre `SHOPEE_APP_ID`,
   `SHOPEE_APP_SECRET`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `SUPABASE_URL`,
   `SUPABASE_KEY`.
3. Aba Actions > "Rodagem de ofertas Shopee" > Run workflow. No campo de opções
   você pode usar `--dry-run` ou `--only natura`.

## Observações

- O Supabase gratuito pausa o projeto após cerca de uma semana sem uso. Com as
  rodagens diárias isso não acontece; se pausar, use "Resume project" no painel.
- Religar o WhatsApp Cloud API: `WHATSAPP_ENABLED=true` + variáveis do WhatsApp.
- O preço "De" é calculado a partir do % de desconto que a Shopee mostra, então
  pode diferir alguns centavos do preço riscado da página.
