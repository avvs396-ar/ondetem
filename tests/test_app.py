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


if __name__ == "__main__":
    unittest.main()
