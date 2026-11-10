# Mestre dos Achados — bot de ofertas Shopee + Rakuten -> Telegram

Busca ofertas na Shopee e na Rakuten e posta no canal do Telegram, com a foto do
produto em cima e o texto no modelo do WhatsApp (você copia e cola no grupo).
O envio pelo WhatsApp Cloud API fica **desligado** (evita custo no cartão).

## O que cada rodagem faz

**Shopee** (todas as rodagens)

| Bloco | Quantas | Como escolhe |
|---|---|---|
| Boticário, Natura, Wepink, Eudora | até 7 cada | maior desconto, depois maior comissão |
| Top desconto / vendas / comissão | 8 / 7 / 7 | critério do nome, com filtros de qualidade |

**Total da Shopee: 50 produtos por rodagem** (28 das marcas + 22 das listas gerais). Se as marcas não
completarem a cota (ex.: Wepink vazia), o que faltar vai para o top desconto.

**Rakuten** (rodagens das 5h e das 12h)

| Bloco | Quantas | Como escolhe |
|---|---|---|
| Netshoes | 30 (70% tênis) | **nota por produto** (abaixo) |
| Zattini | 30 (70% tênis) | **nota por produto** (abaixo) |
| Lojas de time (LojaNBA, Santos, São Paulo, Timão, Inter) | 2 cada | a mesma nota, com um produto de cada categoria |
| Cruzeiro Store | 5 | a mesma nota |
| Netshoes: campanhas de comissão | até 5 por campanha ativa | modelos com comissão especial, no topo e dentro dos 30 (veja abaixo) |

**A nota por produto** (em `core/rakuten_rules.py`, tudo editável no topo do arquivo):

1. Filtros: só BRL, sem infantil (feminino e unissex entram), só as categorias da lista (tênis, camiseta,
   camisa, moletom, jaqueta, bermuda, legging, mochila, relógio, chuteira), marca conhecida (só Netshoes e
   Zattini), preço dentro da faixa "ok" da categoria (`PRICE_RANGES`; as lojas de time têm faixas maiores) e
   desconto real do feed de no máximo 75%.
2. Pontos: modelo queridinho (`POPULAR_MODELS`), marca conhecida, desconto real do feed (as lojas de time
   informam), preço bem abaixo dos parecidos (mesma marca e categoria) e preço na metade de baixo da faixa.
3. Variedade: tênis de uma marca por vez (em rodadas) e o resto por categoria; um post por produto, não por tamanho.
4. O `--dry-run` mostra a nota de cada produto, para ajustar os pesos olhando o resultado.

- Netshoes e Zattini não informam preço promocional no feed (o `saleprice` vem 0 ou igual ao `price`): esses
  posts mostram só "Por R$ X", sem a linha "De". O "De" e o desconto do site vêm da vitrine e de cupom/pix,
  e não aparecem no feed.
- **Cupons da Rakuten** não saem mais sozinhos: vão **junto dos produtos** em que se aplicam
  (cupom da loja inteira, ou da marca do produto). Cupons que dependem de lista ou de valor do
  carrinho ("leve um brinde acima de R$ 239") não são usados. O preço final com cupom não é calculado.
- A Netshoes e a Zattini não informam preço promocional no feed (o `saleprice` vem 0 ou igual ao
  `price`), então esses posts mostram só "Por R$ X", sem a linha "De".
- Filtros da Shopee: `core/selector.py`. Filtros da Rakuten (anunciantes liberados,
  termos de busca, faixas de preço, nota, modelos queridinhos, campanhas): `core/rakuten_rules.py`.
- Uma oferta enviada não volta por `COOLDOWN_DAYS` dias (padrão 3).
- Se um bloco não tiver ofertas boas e novas, o bot posta as que achar e avisa no log.
- Se a Rakuten falhar (token, limite), só ela fica de fora: a Shopee segue normal.

## Comandos

```
python main.py                          # Shopee
python main.py --rakuten                # Shopee + Rakuten
python main.py --dry-run                # só MOSTRA os posts (não envia nem grava)
python main.py --only natura,vendas     # só alguns blocos
python main.py --only netshoes,zattini --dry-run
python -m unittest tests.test_logic tests.test_rakuten -v   # testes das regras
python test_marcas.py                   # lojas/vendedores por marca na Shopee (só leitura)
python test_rakuten.py                  # o que a sua conta da Rakuten enxerga (só leitura)
python diagnostico_feed.py              # por que Netshoes/Zattini não têm promoção no feed (só leitura)
python diagnostico_produtos.py          # como produtos de links da Netshoes aparecem no feed (só leitura)
```

Blocos da Shopee: `boticario, natura, wepink, eudora, desconto, vendas, comissao`.
Blocos da Rakuten: `netshoes, zattini, times`.

## Campanhas de comissão especial (Netshoes)

No painel da Rakuten (anunciante > Ofertas), a Netshoes anuncia janelas curtas em que paga
15% de comissão (contra 5% da base) por modelos específicos. Enquanto a janela está aberta,
o bot busca esses modelos e os põe no topo do bloco da Netshoes. A comissão **nunca** aparece
no post. As campanhas ficam em `CAMPAIGNS`, no `core/rakuten_rules.py`: para incluir uma nova,
copie um bloco e ajuste nome, termos de busca e datas (em UTC; Brasília = UTC-3).
Campanhas de lista de SKUs ("Lista Especial") não dá para reconhecer pelo nome.

## Configuração (.env)

1. `cp .env.example .env` e preencha Shopee, Telegram e Supabase.
2. No Supabase (SQL Editor), rode uma vez `sql/migracao_supabase.sql`.
3. Rakuten (opcional), duas linhas no `.env`:
   - `RAKUTEN_ACCOUNT_ID=` o SID do site (painel da Rakuten);
   - `RAKUTEN_TOKEN_KEY=` o resultado do comando abaixo, trocando ID e SECRET pelo
     Client ID e Client Secret da sua Application no portal de desenvolvedor:
     `[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes('ID:SECRET'))`
   - O token da Rakuten dura 1 hora e o bot pede um novo sozinho a cada rodagem.
4. Teste: `python main.py --dry-run --only natura` e `python main.py --dry-run --only netshoes,zattini`.

## Agendamento (GitHub Actions)

`.github/workflows/scheduler.yml` roda 7 vezes por dia (5h, 7h30, 10h, 12h, 15h, 17h
e 19h de Brasília; cada rodagem começa ~10 min antes por causa dos atrasos do GitHub).
A Rakuten entra nas rodagens das 5h e das 12h (`--rakuten`).

Secrets do repositório (Settings > Secrets and variables > Actions):
`SHOPEE_APP_ID`, `SHOPEE_APP_SECRET`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`,
`SUPABASE_URL`, `SUPABASE_KEY` e, para a Rakuten, `RAKUTEN_TOKEN_KEY` e
`RAKUTEN_ACCOUNT_ID`. Sem os dois da Rakuten, as rodagens seguem só com a Shopee.

Rodar à mão: aba Actions > "Rodagem de ofertas Shopee" > Run workflow. No campo de
opções use `--dry-run`, `--rakuten` ou `--only natura,netshoes`.

## Observações

- O Supabase gratuito pausa o projeto após cerca de uma semana sem uso. Com as
  rodagens diárias isso não acontece; se pausar, use "Resume project" no painel.
- O feed da Rakuten não informa estoque nem tamanho disponível: um produto pode ter
  esgotado quando o post sair.
- O preço "De" da Shopee é calculado a partir do % de desconto; o da Rakuten é o preço real do feed.
- A `token-key` da Rakuten vale como senha (é o Client ID e o Secret codificados em
  base64, não criptografados): nunca a coloque no chat nem no código.
- Religar o WhatsApp Cloud API: `WHATSAPP_ENABLED=true` + variáveis do WhatsApp.
