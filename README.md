# Validade na Loja — Brasil Cacau

SaaS multi-loja de controle de validade para lojas Brasil Cacau. Site responsivo
(funciona como app em iOS e Android via PWA), com entrada de dados por foto da
etiqueta ou do carimbo da caixa, lida por modelo de visão (Anthropic).

## Como funciona

1. O funcionário fotografa a etiqueta/carimbo da caixa na tela **Capturar**.
2. O servidor envia a foto para a API de visão, que devolve código, produto,
   lote, quantidade e validade. A descrição é casada com a base de ~150 produtos
   (com tolerância a carimbos borrados) para trazer a categoria.
3. O funcionário confere, corrige se necessário e salva. O lote entra no
   **Estoque** da loja, ordenado por vencimento (vencido / ≤30d / ≤60d / ok).
4. Um cron diário compara as validades com os limiares configurados pela loja
   (padrão 60, 30, 15 e 7 dias) e envia um resumo por **WhatsApp** e **e-mail**.
   Cada lote é avisado uma única vez por faixa.
5. Itens vendidos/retirados são marcados como **zerados** e saem dos alertas
   (reversível).

Cada usuário pertence a uma loja; toda consulta e ação sobre lotes filtra pelo
`loja_id` da sessão no servidor — uma loja nunca enxerga dados de outra.

## Estrutura

```
app.py            rotas, auth, leitura de etiqueta, job de alertas
models.py         Loja, Usuario, Produto, Lote, AlertaEnviado
notificacoes.py   WhatsApp (CallMeBot) e e-mail (SMTP) — camada isolada
data/produtos.txt base de produtos (semeada automaticamente no 1º boot)
templates/        páginas Jinja mobile-first
static/           CSS, JS (câmera + redimensionamento), PWA (manifest, sw, ícones)
render.yaml       blueprint do Render (web + Postgres + cron)
```

## Rodar localmente

```bash
pip install -r requirements.txt
cp .env.example .env   # edite ANTHROPIC_API_KEY e ADMIN_SENHA
export $(grep -v '^#' .env | xargs)
python app.py          # http://localhost:5000
```

Sem `DATABASE_URL` de Postgres, usa SQLite local (`validade.db`).

## Deploy no Render

1. Suba este diretório para um repositório Git (GitHub).
2. No Render: **New → Blueprint**, aponte para o repositório. O `render.yaml`
   cria o web service, o Postgres gratuito e o cron job.
3. No painel do web service, preencha as variáveis marcadas como `sync: false`:
   - `ANTHROPIC_API_KEY` — chave da API Anthropic (console.anthropic.com)
   - `ADMIN_SENHA` — senha da área /admin
   - `SMTP_HOST/USER/PASS` e `EMAIL_FROM` — opcional; sem isso, só WhatsApp
4. No cron job `validade-alertas`, defina `URL_ALERTAS` com a URL pública +
   token, ex.: `https://SEU-APP.onrender.com/tasks/enviar-alertas?token=VALOR_DO_CRON_TOKEN`
   (o valor de `CRON_TOKEN` aparece nas env vars do web service).
5. Acesse `https://SEU-APP.onrender.com/admin/login`, crie as lojas e os
   usuários de cada uma.
6. Cada loja entra em **Alertas** e configura: dias de antecedência, e-mails e
   WhatsApp (número + apikey do CallMeBot — o número autoriza o bot uma única
   vez seguindo callmebot.com).

No plano gratuito o serviço "dorme" após inatividade; a primeira visita do dia
demora ~30s para acordar. O cron acorda o serviço sozinho antes de rodar.

## Custos

- Render free (web + Postgres + cron): R$ 0. Starter (~US$ 7/mês) elimina o sleep.
- Leitura de etiqueta: centavos por foto (a imagem é redimensionada no celular
  antes do envio para reduzir custo).
- CallMeBot: gratuito, adequado para piloto.

## Evoluções recomendadas antes de vender como produto

- **WhatsApp oficial (Meta Cloud API)** no lugar do CallMeBot — necessário para
  uso comercial em escala; só exige trocar `enviar_whatsapp` em `notificacoes.py`.
- Guardar a foto original de cada leitura (Render Disk ou S3/Backblaze) para
  auditoria.
- Painel consolidado da rede (visão admin de todas as lojas).
- Baixa parcial de quantidade (hoje o zerar é do lote inteiro).
