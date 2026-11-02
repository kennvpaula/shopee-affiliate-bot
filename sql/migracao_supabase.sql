-- Rode UMA vez no SQL Editor do Supabase (projeto achados-shopee).
-- Pode rodar de novo sem problema: os comandos são "if not exists".

-- Guarda de qual bloco veio cada oferta (BOTICÁRIO, NATURA, TOP VENDAS...)
alter table sent_offers add column if not exists category text;

-- Deixa rápida a consulta "o que foi enviado nos últimos dias"
create index if not exists sent_offers_sent_at_idx on sent_offers (sent_at);
