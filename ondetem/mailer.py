"""Envio transacional de e-mails via HTTPS (Brevo API / Resend API), SMTP ou console local."""

from __future__ import annotations

import json
import os
import smtplib
import ssl
import urllib.error
import urllib.request
from email.message import EmailMessage

from ondetem.security import esc


def _smtp_config() -> tuple[str, int, str, str, str]:
    host = os.environ.get("SMTP_HOST", "smtp.gmail.com").strip()
    try:
        port = int(os.environ.get("SMTP_PORT", "465").strip() or "465")
    except ValueError:
        port = 465
    user = os.environ.get("SMTP_USER", "").strip()
    password = os.environ.get("SMTP_PASS", "").replace(" ", "").strip()
    sender = os.environ.get("MAIL_FROM", "").strip() or (f"OndeTem Manaus <{user}>" if user else "")
    return host, port, user, password, sender


def mailer_backend_name() -> str:
    if os.environ.get("BREVO_API_KEY", "").strip():
        return "brevo"
    if os.environ.get("RESEND_API_KEY", "").strip():
        return "resend"
    _, _, user, password, _ = _smtp_config()
    if user and password:
        return "smtp"
    return "console"


def _send_email(to_email: str, subject: str, html_body: str, plain_body: str) -> bool:
    """Prioriza APIs HTTPS (Brevo -> Resend) que nunca são bloqueadas pelo Render Free."""
    # 1. Brevo HTTPS API (300 e-mails/dia grátis, envia para qualquer e-mail sem domínio pago)
    brevo_key = os.environ.get("BREVO_API_KEY", "").strip()
    if brevo_key:
        sender_email = (
            os.environ.get("BREVO_SENDER_EMAIL", "").strip()
            or os.environ.get("SMTP_USER", "").strip()
        )
        sender_name = os.environ.get("BREVO_SENDER_NAME", "OndeTem Manaus").strip()
        payload = json.dumps(
            {
                "sender": {"name": sender_name, "email": sender_email},
                "to": [{"email": to_email}],
                "subject": subject,
                "htmlContent": html_body,
                "textContent": plain_body,
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            "https://api.brevo.com/v3/smtp/email",
            data=payload,
            headers={
                "api-key": brevo_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "OndeTem/3.5.2",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                print(f"[OndeTem Mailer - Brevo] E-mail enviado para {to_email} (HTTP {resp.status})")
                return 200 <= resp.status < 300
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            print(f"[OndeTem Mailer - ERRO Brevo {exc.code}] {detail}")
            return False
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            print(f"[OndeTem Mailer - ERRO Brevo] {exc}")
            return False

    # 2. Resend HTTPS API
    resend_key = os.environ.get("RESEND_API_KEY", "").strip()
    if resend_key:
        sender = os.environ.get("MAIL_FROM", "OndeTem Manaus <onboarding@resend.dev>").strip()
        payload = json.dumps(
            {"from": sender, "to": [to_email], "subject": subject, "html": html_body}
        ).encode("utf-8")
        req = urllib.request.Request(
            "https://api.resend.com/emails",
            data=payload,
            headers={
                "Authorization": f"Bearer {resend_key}",
                "Content-Type": "application/json",
                "User-Agent": "OndeTem/3.5.2",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                print(f"[OndeTem Mailer - Resend] E-mail enviado para {to_email} (HTTP {resp.status})")
                return 200 <= resp.status < 300
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            print(f"[OndeTem Mailer - ERRO Resend {exc.code}] {detail}")
            return False
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            print(f"[OndeTem Mailer - ERRO Resend] {exc}")
            return False

    # 3. SMTP (para VPS / uso local onde portas 465/587 são liberadas)
    host, port, user, password, smtp_sender = _smtp_config()
    if user and password:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = smtp_sender
        msg["To"] = to_email
        msg.set_content(plain_body)
        msg.add_alternative(html_body, subtype="html")
        ctx = ssl.create_default_context()
        try:
            if port == 465:
                with smtplib.SMTP_SSL(host, port, timeout=15, context=ctx) as server:
                    server.login(user, password)
                    server.send_message(msg)
            else:
                with smtplib.SMTP(host, port, timeout=15) as server:
                    server.starttls(context=ctx)
                    server.login(user, password)
                    server.send_message(msg)
            print(f"[OndeTem Mailer - SMTP] E-mail enviado para {to_email}")
            return True
        except Exception as exc:
            print(f"[OndeTem Mailer - ERRO SMTP] Falha ao enviar para {to_email}: {exc}")
            return False

    print(f"[OndeTem Mailer - DEV] Para: {to_email} | Assunto: {subject}\n{plain_body}")
    return True


def send_password_reset_email(to_email: str, user_name: str, reset_url: str) -> bool:
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
      <p style="font-size:13px;color:#5A6B7C;">Este link vale por <strong>30 minutos</strong> e só pode ser usado uma vez. Se você não solicitou a troca, ignore este e-mail.</p>
      <hr style="border:0;border-top:1px solid #DBE6EB;margin:20px 0;">
      <p style="font-size:12px;color:#5A6B7C;">Link direto: {esc(reset_url)}</p>
    </div>
    """
    plain = (
        f"Olá, {first_name}!\n\n"
        f"Use o link abaixo (válido por 30 minutos) para redefinir sua senha no OndeTem:\n{reset_url}\n"
    )
    return _send_email(to_email, "Redefinição de senha · OndeTem Manaus", html_body, plain)


def send_verification_email(to_email: str, user_name: str, verify_url: str) -> bool:
    first_name = (user_name or "").split()[0] if user_name else "Olá"
    html_body = f"""
    <div style="font-family:system-ui,-apple-system,Segoe UI,Arial,sans-serif;max-width:540px;margin:0 auto;padding:24px;color:#133C55;">
      <h2 style="margin:0 0 12px;color:#133C55;">Onde<span style="color:#F07830;">Tem</span> · Manaus</h2>
      <p>Bem-vindo(a), <strong>{esc(first_name)}</strong>!</p>
      <p>Confirme seu e-mail para ativar sua conta completa e poder publicar avaliações no OndeTem:</p>
      <p style="margin:24px 0;">
        <a href="{esc(verify_url)}" style="display:inline-block;background:#1E8E5A;color:#ffffff;text-decoration:none;font-weight:700;padding:12px 22px;border-radius:10px;">
          Confirmar meu e-mail
        </a>
      </p>
      <p style="font-size:13px;color:#5A6B7C;">Este link é válido por <strong>24 horas</strong>.</p>
      <hr style="border:0;border-top:1px solid #DBE6EB;margin:20px 0;">
      <p style="font-size:12px;color:#5A6B7C;">Link direto: {esc(verify_url)}</p>
    </div>
    """
    plain = (
        f"Bem-vindo(a), {first_name}!\n\n"
        f"Confirme seu e-mail no OndeTem acessando o link abaixo (válido por 24 horas):\n{verify_url}\n"
    )
    return _send_email(to_email, "Confirme seu e-mail · OndeTem Manaus", html_body, plain)
