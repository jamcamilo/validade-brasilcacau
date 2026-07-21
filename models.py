# -*- coding: utf-8 -*-
"""Modelos do banco — multi-tenant por loja_id em todas as tabelas de dados."""
from datetime import datetime, date
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class Loja(db.Model):
    __tablename__ = "lojas"
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(120), nullable=False)
    ativa = db.Column(db.Boolean, default=True)
    # Configuração de alertas
    dias_alerta = db.Column(db.String(60), default="60,30,15,7")  # limiares em dias
    emails_alerta = db.Column(db.String(400), default="")         # separados por vírgula
    whatsapp_numero = db.Column(db.String(30), default="")        # +55DDDNUMERO
    whatsapp_apikey = db.Column(db.String(60), default="")        # CallMeBot apikey
    criada_em = db.Column(db.DateTime, default=datetime.utcnow)

    usuarios = db.relationship("Usuario", backref="loja", lazy=True)
    lotes = db.relationship("Lote", backref="loja", lazy=True)

    def limiares(self):
        out = []
        for p in (self.dias_alerta or "").split(","):
            p = p.strip()
            if p.isdigit():
                out.append(int(p))
        return sorted(set(out), reverse=True) or [30, 15, 7]


class Usuario(db.Model):
    __tablename__ = "usuarios"
    id = db.Column(db.Integer, primary_key=True)
    loja_id = db.Column(db.Integer, db.ForeignKey("lojas.id"), nullable=False)
    email = db.Column(db.String(160), unique=True, nullable=False)
    senha_hash = db.Column(db.String(300), nullable=False)
    nome = db.Column(db.String(120), default="")
    criado_em = db.Column(db.DateTime, default=datetime.utcnow)


class Produto(db.Model):
    """Base global de produtos (compartilhada entre todas as lojas)."""
    __tablename__ = "produtos"
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(200), unique=True, nullable=False)
    categoria = db.Column(db.String(120), default="")
    ativo = db.Column(db.Boolean, default=True)


class Lote(db.Model):
    __tablename__ = "lotes"
    id = db.Column(db.Integer, primary_key=True)
    loja_id = db.Column(db.Integer, db.ForeignKey("lojas.id"), nullable=False, index=True)
    produto_id = db.Column(db.Integer, db.ForeignKey("produtos.id"), nullable=True)
    descricao = db.Column(db.String(200), nullable=False)   # como foi lida/confirmada
    categoria = db.Column(db.String(120), default="")
    codigo_item = db.Column(db.String(30), default="")
    lote = db.Column(db.String(30), default="")
    quantidade = db.Column(db.Integer, default=0)
    validade = db.Column(db.Date, nullable=True, index=True)
    ean = db.Column(db.String(20), default="")
    zerado = db.Column(db.Boolean, default=False, index=True)
    registrado_em = db.Column(db.DateTime, default=datetime.utcnow)
    registrado_por = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=True)

    produto = db.relationship("Produto", lazy=True)

    def dias_restantes(self):
        if not self.validade:
            return None
        return (self.validade - date.today()).days


class AlertaEnviado(db.Model):
    """Evita alertar duas vezes o mesmo lote no mesmo limiar."""
    __tablename__ = "alertas_enviados"
    id = db.Column(db.Integer, primary_key=True)
    lote_id = db.Column(db.Integer, db.ForeignKey("lotes.id"), nullable=False, index=True)
    limiar = db.Column(db.Integer, nullable=False)  # ex.: 30 (dias) ou -1 (vencido)
    enviado_em = db.Column(db.DateTime, default=datetime.utcnow)
    __table_args__ = (db.UniqueConstraint("lote_id", "limiar", name="uq_lote_limiar"),)
