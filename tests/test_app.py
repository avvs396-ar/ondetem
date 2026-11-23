"""Testes automatizados do OndeTem 3.0 (FastAPI, PostgreSQL/SQLite e segurança)."""

from __future__ import annotations

import io
import re
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from ondetem.db import translate_sql_for_postgres
from ondetem.storage import build_cloudinary_signature, resolve_image_url
from ondetem.security import (
    clean_whatsapp,
    normalize_text,
    password_hash,
    password_matches,
    safe_destination,
    sanitize_image,
)
from ondetem.web import create_app


class SecurityAndDbUnitTests(unittest.TestCase):
    def test_password_hashing(self):
        stored = password_hash("SenhaForte123!")
        self.assertTrue(password_matches("SenhaForte123!", stored))
        self.assertFalse(password_matches("Errada123!", stored))

    def test_accent_normalization(self):
        self.assertEqual(normalize_text("Elétrica / Móveis"), "eletrica / moveis")

    def test_safe_destination_blocks_open_redirect(self):
        self.assertEqual(safe_destination("/buscar?q=eletricista"), "/buscar?q=eletricista")
        self.assertEqual(safe_destination("https://evil.com"), "/")
        self.assertEqual(safe_destination("//evil.com"), "/")

    def test_clean_whatsapp(self):
        self.assertEqual(clean_whatsapp("(92) 99123-4567"), "92991234567")
        self.assertEqual(clean_whatsapp("+55 92 99123-4567"), "92991234567")
        self.assertEqual(clean_whatsapp("123"), "")

    def test_sanitize_image_valid_and_invalid(self):
        buf = io.BytesIO()
        Image.new("RGB", (400, 300), color=(240, 120, 48)).save(buf, format="JPEG")
        cleaned, ext = sanitize_image(buf.getvalue())
        self.assertIsNotNone(cleaned)
        self.assertEqual(ext, ".jpg")
        bad, bad_ext = sanitize_image(b"not an image")
        self.assertIsNone(bad)
        self.assertEqual(bad_ext, "")

    def test_postgres_placeholder_translation(self):
        sql = "SELECT * FROM users WHERE email = ? AND role = ?"
        self.assertEqual(
            translate_sql_for_postgres(sql),
            "SELECT * FROM users WHERE email = %s AND role = %s",
        )



    def test_cloudinary_signature_and_url_resolution(self):
        sig = build_cloudinary_signature({"public_id": "ondetem/x", "timestamp": "1700000000"}, "secret")
        self.assertEqual(len(sig), 40)
        self.assertEqual(resolve_image_url("uploads/a.jpg"), "/static/uploads/a.jpg")
        self.assertEqual(
            resolve_image_url("https://res.cloudinary.com/demo/image/upload/a.jpg"),
            "https://res.cloudinary.com/demo/image/upload/a.jpg",
        )


class FastApiIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.TemporaryDirectory()
        cls.db_path = Path(cls.tmpdir.name) / "test.db"
        cls.app = create_app(db_path=cls.db_path)
        cls.client_cm = TestClient(cls.app)
        cls.client = cls.client_cm.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client_cm.__exit__(None, None, None)
        cls.tmpdir.cleanup()

    def test_home_and_security_headers(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("OndeTem", resp.text)
        self.assertEqual(resp.headers.get("X-Frame-Options"), "DENY")
        self.assertEqual(resp.headers.get("X-Content-Type-Options"), "nosniff")
        self.assertIn("Content-Security-Policy", resp.headers)

    def test_health_and_json_api(self):
        health = self.client.get("/api/health")
        self.assertEqual(health.status_code, 200)
        data = health.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["database"], "sqlite")
        self.assertGreaterEqual(data["professionals"], 8)

        api = self.client.get("/api/profissionais?q=moveis")
        self.assertEqual(api.status_code, 200)
        self.assertGreaterEqual(api.json()["count"], 1)

    def test_accent_insensitive_search(self):
        resp = self.client.get("/buscar?q=moveis")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("João Pereira", resp.text)

    def test_login_review_and_chat_flow(self):
        login = self.client.post(
            "/entrar",
            data={"email": "cliente@ondetem.local", "password": "Demo123!"},
            follow_redirects=False,
        )
        self.assertEqual(login.status_code, 303)
        self.assertIn("session", self.client.cookies)

        profile = self.client.get("/perfil/4")
        self.assertEqual(profile.status_code, 200)
        self.assertIn("Chamar no WhatsApp", profile.text)
        match = re.search(r'name="csrf" value="([^"]+)"', profile.text)
        self.assertIsNotNone(match)
        csrf = match.group(1)

        # Publica avaliação
        rev = self.client.post(
            "/avaliar/4",
            data={"csrf": csrf, "rating": "5", "comment": "Atendimento excelente em Manaus!"},
            follow_redirects=False,
        )
        self.assertEqual(rev.status_code, 303)

        # Inicia conversa e envia mensagem
        start = self.client.post("/iniciar/4", data={"csrf": csrf}, follow_redirects=False)
        self.assertEqual(start.status_code, 303)
        conv_url = start.headers["location"]
        msg = self.client.post(
            conv_url,
            data={"csrf": csrf, "body": "Olá! Preciso de um orçamento no Parque Dez."},
            follow_redirects=True,
        )
        self.assertEqual(msg.status_code, 200)
        self.assertIn("Preciso de um orçamento no Parque Dez.", msg.text)



    def test_professional_avatar_upload(self):
        self.client.post(
            "/entrar",
            data={"email": "carlos@ondetem.local", "password": "Demo123!"},
            follow_redirects=False,
        )
        panel = self.client.get("/painel")
        self.assertEqual(panel.status_code, 200)
        self.assertIn("Foto de perfil", panel.text)
        csrf = re.search(r'name="csrf" value="([^"]+)"', panel.text).group(1)

        buf = io.BytesIO()
        Image.new("RGB", (600, 400), color=(19, 60, 85)).save(buf, format="JPEG")
        resp = self.client.post(
            "/perfil/foto",
            data={"csrf": csrf},
            files={"avatar": ("foto.jpg", buf.getvalue(), "image/jpeg")},
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 303)



    def test_terms_and_privacy_pages(self):
        t = self.client.get("/termos")
        self.assertEqual(t.status_code, 200)
        self.assertIn("Termos de Uso", t.text)
        p = self.client.get("/privacidade")
        self.assertEqual(p.status_code, 200)
        self.assertIn("LGPD", p.text)

    def test_signup_requires_terms_and_lgpd_delete_account(self):
        # Sem aceitar termos deve dar 400
        bad = self.client.post(
            "/cadastro",
            data={"name": "Teste LGPD", "email": "lgpd@ondetem.local", "password": "SenhaForte123!", "role": "cliente"},
        )
        self.assertEqual(bad.status_code, 400)

        # Extrai desafio anti-robô da página /cadastro
        signup_page = self.client.get("/cadastro")
        tok = re.search(r'name="captcha_token" value="([^"]+)"', signup_page.text).group(1)
        m_eq = re.search(r'Quanto é (\d+) \+ (\d+)\?', signup_page.text)
        ans = str(int(m_eq.group(1)) + int(m_eq.group(2)))

        # Honeypot preenchido (bot) deve ser barrado
        bot = self.client.post(
            "/cadastro",
            data={
                "name": "Bot Spam",
                "email": "bot@ondetem.local",
                "password": "SenhaForte123!",
                "role": "cliente",
                "accept_terms": "1",
                "website_url": "http://spam.example",
                "captcha_token": tok,
                "captcha_answer": ans,
            },
        )
        self.assertEqual(bot.status_code, 400)

        # Aceitando termos + anti-bot cria conta (inicialmente não verificada)
        ok = self.client.post(
            "/cadastro",
            data={
                "name": "Teste LGPD",
                "email": "lgpd@ondetem.local",
                "password": "SenhaForte123!",
                "role": "cliente",
                "accept_terms": "1",
                "captcha_token": tok,
                "captcha_answer": ans,
            },
            follow_redirects=False,
        )
        self.assertEqual(ok.status_code, 303)

        # Solicita redefinição de senha e testa token real
        forgot = self.client.post("/esqueci-senha", data={"email": "lgpd@ondetem.local"}, follow_redirects=False)
        self.assertEqual(forgot.status_code, 303)

        # Cria token controlado para testar redefinição fim a fim
        from datetime import datetime, timedelta, timezone
        from ondetem.db import get_db
        from ondetem.security import token_hash
        with get_db(db_path=self.db_path) as db:
            uid = db.scalar("SELECT id FROM users WHERE email = ?", ("lgpd@ondetem.local",))
            exp = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat(timespec="seconds")
            db.execute(
                "INSERT INTO password_resets (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
                (token_hash("tok_teste_123"), uid, exp),
            )
        reset = self.client.post(
            "/redefinir-senha",
            data={"token": "tok_teste_123", "password": "NovaSenha456!", "confirm_password": "NovaSenha456!"},
            follow_redirects=False,
        )
        self.assertEqual(reset.status_code, 303)

        # Entra com a nova senha e exclui a conta (LGPD)
        relogin = self.client.post(
            "/entrar",
            data={"email": "lgpd@ondetem.local", "password": "NovaSenha456!"},
            follow_redirects=False,
        )
        self.assertEqual(relogin.status_code, 303)
        conta = self.client.get("/conta")
        self.assertEqual(conta.status_code, 200)
        csrf = re.search(r'name="csrf" value="([^"]+)"', conta.text).group(1)

        deleted = self.client.post(
            "/conta/excluir",
            data={"csrf": csrf, "password": "NovaSenha456!"},
            follow_redirects=False,
        )
        self.assertEqual(deleted.status_code, 303)
        with get_db(db_path=self.db_path) as db:
            gone = db.fetchone("SELECT id FROM users WHERE email = ?", ("lgpd@ondetem.local",))
            self.assertIsNone(gone)



    def test_whatsapp_click_tracking_and_admin_panel(self):
        # Clique no WhatsApp redireciona para wa.me e incrementa contador
        wa = self.client.get("/contato/whatsapp/4", follow_redirects=False)
        self.assertEqual(wa.status_code, 302)
        self.assertIn("https://wa.me/55", wa.headers["location"])

        # Login como cliente demo (liberado como admin local em SQLite)
        self.client.post(
            "/entrar",
            data={"email": "cliente@ondetem.local", "password": "Demo123!"},
            follow_redirects=False,
        )
        adm = self.client.get("/admin")
        self.assertEqual(adm.status_code, 200)
        self.assertIn("Gestão e Métricas de Manaus", adm.text)
        csrf = re.search(r'name="csrf" value="([^"]+)"', adm.text).group(1)

        # Alterna selo Verificado do profissional 4
        tog = self.client.post("/admin/verificar/4", data={"csrf": csrf}, follow_redirects=False)
        self.assertEqual(tog.status_code, 303)



    def test_pwa_manifest_sw_and_icons(self):
        m = self.client.get("/manifest.webmanifest")
        self.assertEqual(m.status_code, 200)
        self.assertEqual(m.json()["display"], "standalone")

        sw = self.client.get("/sw.js")
        self.assertEqual(sw.status_code, 200)
        self.assertEqual(sw.headers.get("service-worker-allowed"), "/")

        for icon in ("/static/icon-192.png", "/static/icon-512.png", "/static/apple-touch-icon.png"):
            r = self.client.get(icon)
            self.assertEqual(r.status_code, 200)



    def test_email_verification_unlocks_account(self):
        from datetime import datetime, timedelta, timezone
        from ondetem.db import get_db
        from ondetem.security import token_hash
        with get_db(db_path=self.db_path) as db:
            uid = db.insert_returning_id(
                "INSERT INTO users (name, email, password_hash, role, email_verified, created_at) VALUES (?, ?, ?, 'cliente', 0, ?)",
                ("Novo Usuario", "novo@ondetem.local", password_hash("SenhaForte123!"), "2026-11-22T15:00:00+00:00"),
            )
            exp = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat(timespec="seconds")
            db.execute(
                "INSERT INTO email_verifications (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
                (token_hash("verify_tok_999"), uid, exp),
            )
        res = self.client.get("/verificar-email?token=verify_tok_999", follow_redirects=False)
        self.assertEqual(res.status_code, 303)
        with get_db(db_path=self.db_path) as db:
            val = db.scalar("SELECT email_verified FROM users WHERE id = ?", (uid,))
            self.assertEqual(int(val), 1)



    def test_expanded_professions_available(self):
        home = self.client.get("/")
        self.assertEqual(home.status_code, 200)
        for cat in ("Diarista / Limpeza", "Mecânico / Auto", "Técnico de TI / Informática", "Contador / MEI", "Músico / Eventos"):
            self.assertIn(cat, home.text)


if __name__ == "__main__":
    unittest.main()
