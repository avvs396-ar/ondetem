"""Envio transacional de e-mails (Resend API em produção, log seguro no console em dev)."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from ondetem.security import esc


def mailer_backend_name() -> str:
    return "resend" if os.environ.get("RESEND_API_KEY", "").strip() else "console"


def send_password_reset_email(to_email: str, user_name: str, reset_url: str) -> bool:
    """Envia link de redefinição de senha via Resend (ou registra no console se sem API key)."""
    api_key = os.environ.get("RESEND_API_KEY", "").strip()
    sender = os.environ.get("MAIL_FROM", "OndeTem Manaus <onboarding@resend.dev>").strip()
    first_name = (user_name or "").split()[0] if user_name else "Olá"

    html_body = f"""
    <div style="font-family:system-ui,-apple-system,Segoe UI,Arial,sans-serif;max-width:540px;margin:0 auto;padding:24px;color:#133C55;">
      <h2 style="margin:0 0 12px;color:#133C55;">Onde<span style="color:#F07830;">Tem</span> · Manaus</h2>
      <p>Olá, <strong>{esc(first_name)}</strong>!</p>
      <p>Recebemos um pedido para redefinir a senha da sua conta no OndeTem. Clique no botão abaixo para criar uma nova senha:</p>
      <p style="margin:24px 0;">
        <a href="{esc(reset_url)}" style="display:inline-block;background:#F07830;color:#ffffff;text-decoration:none;font-weight:700;padding:12px 22px;border-radius:10px;">
          Redefinir minha senha
        </a>
      </p>
      <p style="font-size:13px;color:#5A6B7C;">Este link vale por <strong>30 minutos</strong> e só pode ser usado uma vez. Se você não solicitou a troca, pode ignorar este e-mail com segurança.</p>
      <hr style="border:0;border-top:1px solid #DBE6EB;margin:20px 0;">
      <p style="font-size:12px;color:#5A6B7C;">Se o botão não abrir, copie e cole este endereço no navegador:<br>{esc(reset_url)}</p>
    </div>
    """

    if not api_key:
        print(f"[OndeTem Mailer - DEV] Link de redefinição para {to_email}: {reset_url}")
        return True

    payload = json.dumps(
        {
            "from": sender,
            "to": [to_email],
            "subject": "Redefinição de senha · OndeTem Manaus",
            "html": html_body,
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "OndeTem/3.2",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return 200 <= resp.status < 300
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        print(f"[OndeTem Mailer - ERRO] Falha ao enviar e-mail via Resend: {exc}")
        return False
