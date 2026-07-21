# -*- coding: utf-8 -*-
"""Envio de alertas por WhatsApp (CallMeBot) e e-mail (SMTP).

Camada isolada de propósito: quando o produto crescer, troque o CallMeBot
pela API oficial do WhatsApp Business (Meta Cloud API) alterando apenas
`enviar_whatsapp`, sem tocar no resto do sistema.
"""
import os
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from urllib.parse import quote

import requests

log = logging.getLogger(__name__)


def enviar_whatsapp(numero: str, apikey: str, texto: str) -> bool:
    """CallMeBot: o número precisa ter autorizado o bot e possuir apikey própria.
    https://www.callmebot.com/blog/free-api-whatsapp-messages/
    """
    if not numero or not apikey:
        return False
    try:
        url = (
            "https://api.callmebot.com/whatsapp.php"
            f"?phone={quote(numero)}&text={quote(texto)}&apikey={quote(apikey)}"
        )
        r = requests.get(url, timeout=30)
        ok = r.status_code == 200
        if not ok:
            log.warning("CallMeBot retornou %s: %s", r.status_code, r.text[:200])
        return ok
    except Exception as e:
        log.error("Falha WhatsApp: %s", e)
        return False


def enviar_email(destinos: list, assunto: str, corpo_html: str) -> bool:
    host = os.environ.get("SMTP_HOST")
    if not host or not destinos:
        return False
    porta = int(os.environ.get("SMTP_PORT", "587"))
    usuario = os.environ.get("SMTP_USER", "")
    senha = os.environ.get("SMTP_PASS", "")
    remetente = os.environ.get("EMAIL_FROM", usuario)
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = assunto
        msg["From"] = remetente
        msg["To"] = ", ".join(destinos)
        msg.attach(MIMEText(corpo_html, "html", "utf-8"))
        with smtplib.SMTP(host, porta, timeout=30) as s:
            s.starttls()
            if usuario:
                s.login(usuario, senha)
            s.sendmail(remetente, destinos, msg.as_string())
        return True
    except Exception as e:
        log.error("Falha e-mail: %s", e)
        return False


def montar_mensagens(loja_nome: str, grupos: dict):
    """grupos: {limiar: [lotes]} — limiar -1 significa vencido.

    Retorna (texto_whatsapp, html_email).
    """
    linhas_txt, linhas_html = [], []
    for limiar in sorted(grupos.keys()):
        lotes = grupos[limiar]
        if not lotes:
            continue
        titulo = "VENCIDOS" if limiar == -1 else f"Vencem em até {limiar} dias"
        linhas_txt.append(f"\n*{titulo}:*")
        linhas_html.append(f"<h3 style='margin:14px 0 6px'>{titulo}</h3><ul>")
        for l in lotes:
            val = l.validade.strftime("%d/%m/%Y") if l.validade else "—"
            item = f"{l.descricao} — lote {l.lote or '—'} — {l.quantidade} UN — val. {val}"
            linhas_txt.append(f"• {item}")
            linhas_html.append(f"<li>{item}</li>")
        linhas_html.append("</ul>")
    texto = f"⚠️ *Controle de Validade — {loja_nome}*" + "\n".join([""] + linhas_txt)
    html = (
        f"<div style='font-family:sans-serif'><h2>⚠️ Controle de Validade — {loja_nome}</h2>"
        + "".join(linhas_html)
        + "<p style='color:#888;font-size:12px'>Itens marcados como zerados não aparecem aqui. "
        "Acesse o sistema para zerar itens já vendidos/retirados.</p></div>"
    )
    return texto, html
