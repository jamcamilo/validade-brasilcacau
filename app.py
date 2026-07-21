# -*- coding: utf-8 -*-
"""Controle de Validade — Brasil Cacau (SaaS multi-loja)

Site responsivo (PWA) em Flask, pensado para deploy no Render.
- Entrada por foto da etiqueta/carimbo, lida por modelo de visão (Anthropic).
- Dados isolados por loja (todo acesso a Lote filtra por loja_id da sessão).
- Alertas diários por WhatsApp e e-mail via endpoint de cron.
"""
import os
import re
import json
import base64
import logging
import unicodedata
from datetime import datetime, date
from functools import wraps

import requests
from flask import (
    Flask, render_template, request, redirect, url_for,
    session, jsonify, abort, flash
)
from werkzeug.security import generate_password_hash, check_password_hash

from models import db, Loja, Usuario, Produto, Lote, AlertaEnviado
from notificacoes import enviar_whatsapp, enviar_email, montar_mensagens

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "troque-esta-chave")

_db_url = os.environ.get("DATABASE_URL", "sqlite:///validade.db")
# Render entrega postgres:// ; SQLAlchemy exige postgresql://
if _db_url.startswith("postgres://"):
    _db_url = _db_url.replace("postgres://", "postgresql://", 1)
app.config["SQLALCHEMY_DATABASE_URI"] = _db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024  # 8 MB por foto

db.init_app(app)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
CRON_TOKEN = os.environ.get("CRON_TOKEN", "")
ADMIN_SENHA = os.environ.get("ADMIN_SENHA", "")


# ─── Bootstrap: cria tabelas e semeia produtos ────────────────────────────
def _seed_produtos():
    if Produto.query.first():
        return
    caminho = os.path.join(os.path.dirname(__file__), "data", "produtos.txt")
    if not os.path.exists(caminho):
        return
    with open(caminho, encoding="utf-8") as f:
        for linha in f:
            linha = linha.strip()
            if not linha or "|" not in linha:
                continue
            nome, categoria = [p.strip() for p in linha.split("|", 1)]
            db.session.add(Produto(nome=nome, categoria=categoria))
    db.session.commit()
    log.info("Base de produtos semeada.")


with app.app_context():
    db.create_all()
    _seed_produtos()


# ─── Auth ─────────────────────────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("usuario_id"):
            return redirect(url_for("login", proximo=request.path))
        return f(*args, **kwargs)
    return wrapper


def usuario_atual():
    uid = session.get("usuario_id")
    return db.session.get(Usuario, uid) if uid else None


@app.context_processor
def inject_globals():
    return {"usuario": usuario_atual(), "ano": date.today().year}


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        senha = request.form.get("senha") or ""
        u = Usuario.query.filter_by(email=email).first()
        if u and check_password_hash(u.senha_hash, senha) and u.loja.ativa:
            session["usuario_id"] = u.id
            session["loja_id"] = u.loja_id
            return redirect(request.args.get("proximo") or url_for("capturar"))
        flash("E-mail ou senha inválidos.")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ─── Leitura da etiqueta (visão) ──────────────────────────────────────────
PROMPT_LEITURA = (
    "Esta é a foto de uma caixa de produto Brasil Cacau. A identificação pode ser "
    "uma etiqueta branca impressa ou um carimbo de tinta direto no papelão, às vezes "
    "girada, borrada ou com baixo contraste. Extraia os campos: "
    "codigo (número do item, ~10 dígitos), descricao (nome do produto), "
    "lote (após 'L:'), quantidade (número inteiro antes de 'UN'), "
    "validade (data após 'VAL:' no formato DD/MM/AAAA) e ean (código de barras, se legível). "
    "Responda SOMENTE com um objeto JSON com essas chaves. Campos ilegíveis = null. "
    "Sem markdown, sem texto adicional."
)


def _norm(s):
    s = unicodedata.normalize("NFD", (s or "").upper())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = re.sub(r"[^A-Z0-9 .]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _match_produto(descricao):
    alvo = _norm(descricao)
    if not alvo:
        return None, 0.0
    produtos = Produto.query.filter_by(ativo=True).all()
    exato = next((p for p in produtos if _norm(p.nome) == alvo), None)
    if exato:
        return exato, 1.0
    tokens_alvo = set(alvo.split())
    melhor, melhor_score = None, 0.0
    for p in produtos:
        tokens_p = set(_norm(p.nome).split())
        inter = len(tokens_alvo & tokens_p)
        score = inter / max(len(tokens_alvo), len(tokens_p))
        if score > melhor_score:
            melhor, melhor_score = p, score
    if melhor_score >= 0.5:
        return melhor, melhor_score
    return None, melhor_score


@app.route("/api/ler-etiqueta", methods=["POST"])
@login_required
def api_ler_etiqueta():
    if not ANTHROPIC_API_KEY:
        return jsonify({"erro": "ANTHROPIC_API_KEY não configurada no servidor."}), 500
    arq = request.files.get("foto")
    if not arq:
        return jsonify({"erro": "Nenhuma foto recebida."}), 400
    dados = arq.read()
    media_type = arq.mimetype or "image/jpeg"
    b64 = base64.b64encode(dados).decode()

    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": ANTHROPIC_MODEL,
                "max_tokens": 800,
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "image",
                         "source": {"type": "base64", "media_type": media_type, "data": b64}},
                        {"type": "text", "text": PROMPT_LEITURA},
                    ],
                }],
            },
            timeout=90,
        )
        resp.raise_for_status()
        corpo = resp.json()
        texto = "\n".join(b.get("text", "") for b in corpo.get("content", [])
                          if b.get("type") == "text")
        texto = re.sub(r"```json|```", "", texto).strip()
        lido = json.loads(texto)
    except Exception as e:
        log.error("Falha na leitura: %s", e)
        return jsonify({"erro": "Não foi possível ler a etiqueta. Tente outra foto."}), 502

    produto, score = _match_produto(lido.get("descricao"))
    return jsonify({
        "codigo": lido.get("codigo") or "",
        "descricao_lida": lido.get("descricao") or "",
        "descricao": produto.nome if produto else (lido.get("descricao") or ""),
        "produto_id": produto.id if produto else None,
        "categoria": produto.categoria if produto else "",
        "confianca": round(score, 2),
        "lote": lido.get("lote") or "",
        "quantidade": lido.get("quantidade"),
        "validade": lido.get("validade") or "",
        "ean": lido.get("ean") or "",
    })


# ─── Lotes (sempre filtrados pela loja da sessão) ─────────────────────────
def _parse_validade(txt):
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})", txt or "")
    if not m:
        return None
    try:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None


@app.route("/api/lotes", methods=["POST"])
@login_required
def api_criar_lote():
    d = request.get_json(force=True)
    descricao = (d.get("descricao") or "").strip()
    if not descricao:
        return jsonify({"erro": "Descrição obrigatória."}), 400
    produto, _ = _match_produto(descricao)
    lote = Lote(
        loja_id=session["loja_id"],
        produto_id=produto.id if produto else None,
        descricao=produto.nome if produto else descricao,
        categoria=produto.categoria if produto else (d.get("categoria") or ""),
        codigo_item=(d.get("codigo") or "")[:30],
        lote=(d.get("lote") or "")[:30],
        quantidade=int(d.get("quantidade") or 0),
        validade=_parse_validade(d.get("validade")),
        ean=(d.get("ean") or "")[:20],
        registrado_por=session["usuario_id"],
    )
    db.session.add(lote)
    db.session.commit()
    return jsonify({"ok": True, "id": lote.id})


@app.route("/api/lotes/<int:lote_id>/zerar", methods=["POST"])
@login_required
def api_zerar(lote_id):
    lote = Lote.query.filter_by(id=lote_id, loja_id=session["loja_id"]).first()
    if not lote:
        abort(404)
    lote.zerado = not lote.zerado
    db.session.commit()
    return jsonify({"ok": True, "zerado": lote.zerado})


@app.route("/api/lotes/<int:lote_id>", methods=["DELETE"])
@login_required
def api_excluir(lote_id):
    lote = Lote.query.filter_by(id=lote_id, loja_id=session["loja_id"]).first()
    if not lote:
        abort(404)
    AlertaEnviado.query.filter_by(lote_id=lote.id).delete()
    db.session.delete(lote)
    db.session.commit()
    return jsonify({"ok": True})


# ─── Páginas ──────────────────────────────────────────────────────────────
@app.route("/")
def raiz():
    return redirect(url_for("capturar") if session.get("usuario_id") else url_for("login"))


@app.route("/capturar")
@login_required
def capturar():
    return render_template("capturar.html")


@app.route("/estoque")
@login_required
def estoque():
    filtro = request.args.get("f", "ativos")
    q = Lote.query.filter_by(loja_id=session["loja_id"])
    if filtro == "ativos":
        q = q.filter_by(zerado=False)
    elif filtro == "zerados":
        q = q.filter_by(zerado=True)
    lotes = q.order_by(Lote.validade.asc().nullslast()).all()
    return render_template("estoque.html", lotes=lotes, filtro=filtro, hoje=date.today())


@app.route("/config", methods=["GET", "POST"])
@login_required
def config():
    loja = db.session.get(Loja, session["loja_id"])
    if request.method == "POST":
        loja.dias_alerta = re.sub(r"[^0-9,]", "", request.form.get("dias_alerta") or "60,30,15,7")
        loja.emails_alerta = (request.form.get("emails_alerta") or "").strip()
        loja.whatsapp_numero = (request.form.get("whatsapp_numero") or "").strip()
        loja.whatsapp_apikey = (request.form.get("whatsapp_apikey") or "").strip()
        db.session.commit()
        flash("Configurações salvas.")
        return redirect(url_for("config"))
    return render_template("config.html", loja=loja)


# ─── Administração (criação de lojas/usuários) ────────────────────────────
def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not ADMIN_SENHA or session.get("admin") != True:
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return wrapper


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        if ADMIN_SENHA and request.form.get("senha") == ADMIN_SENHA:
            session["admin"] = True
            return redirect(url_for("admin"))
        flash("Senha de administrador incorreta.")
    return render_template("admin_login.html")


@app.route("/admin", methods=["GET", "POST"])
@admin_required
def admin():
    if request.method == "POST":
        acao = request.form.get("acao")
        if acao == "nova_loja":
            nome = (request.form.get("nome") or "").strip()
            if nome:
                db.session.add(Loja(nome=nome))
                db.session.commit()
                flash(f"Loja '{nome}' criada.")
        elif acao == "novo_usuario":
            loja_id = int(request.form.get("loja_id"))
            email = (request.form.get("email") or "").strip().lower()
            senha = request.form.get("senha") or ""
            if email and senha and not Usuario.query.filter_by(email=email).first():
                db.session.add(Usuario(
                    loja_id=loja_id, email=email,
                    nome=(request.form.get("nome") or "").strip(),
                    senha_hash=generate_password_hash(senha),
                ))
                db.session.commit()
                flash(f"Usuário {email} criado.")
            else:
                flash("E-mail já existe ou dados incompletos.")
        elif acao == "alternar_loja":
            loja = db.session.get(Loja, int(request.form.get("loja_id")))
            if loja:
                loja.ativa = not loja.ativa
                db.session.commit()
        return redirect(url_for("admin"))
    lojas = Loja.query.order_by(Loja.nome).all()
    return render_template("admin.html", lojas=lojas)


# ─── Job de alertas (chamado pelo cron do Render) ─────────────────────────
@app.route("/tasks/enviar-alertas")
def tarefa_alertas():
    if not CRON_TOKEN or request.args.get("token") != CRON_TOKEN:
        abort(403)
    resumo = []
    hoje = date.today()
    for loja in Loja.query.filter_by(ativa=True).all():
        limiares = loja.limiares()
        grupos = {}   # {limiar: [lotes]}
        novos = []    # (lote_id, limiar) a registrar
        lotes = Lote.query.filter_by(loja_id=loja.id, zerado=False)\
                          .filter(Lote.validade.isnot(None)).all()
        for l in lotes:
            dias = (l.validade - hoje).days
            limiar_aplicavel = -1 if dias < 0 else next(
                (lim for lim in sorted(limiares) if dias <= lim), None)
            if limiar_aplicavel is None:
                continue
            ja = AlertaEnviado.query.filter_by(
                lote_id=l.id, limiar=limiar_aplicavel).first()
            if ja:
                continue
            grupos.setdefault(limiar_aplicavel, []).append(l)
            novos.append((l.id, limiar_aplicavel))
        if not grupos:
            continue
        texto, html = montar_mensagens(loja.nome, grupos)
        ok_wpp = enviar_whatsapp(loja.whatsapp_numero, loja.whatsapp_apikey, texto)
        destinos = [e.strip() for e in (loja.emails_alerta or "").split(",") if e.strip()]
        ok_mail = enviar_email(destinos, f"⚠️ Validade — {loja.nome}", html)
        if ok_wpp or ok_mail:
            for lote_id, limiar in novos:
                db.session.add(AlertaEnviado(lote_id=lote_id, limiar=limiar))
            db.session.commit()
        resumo.append({"loja": loja.nome, "itens": len(novos),
                       "whatsapp": ok_wpp, "email": ok_mail})
    return jsonify({"executado_em": datetime.utcnow().isoformat(), "lojas": resumo})


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
