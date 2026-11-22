"""Utilidades de segurança: hashing, rate-limit, normalização e sanitização de imagens."""

from __future__ import annotations

import hashlib
import hmac
import html
import io
import math
import os
import re
import time
import unicodedata
import warnings
from collections import defaultdict, deque
from datetime import datetime, timezone
from threading import Lock
from urllib.parse import quote, unquote, urlsplit

try:
    from PIL import Image, ImageOps, UnidentifiedImageError
except ImportError as exc:
    raise SystemExit("Instale a biblioteca de imagens: python -m pip install Pillow") from exc

from ondetem.config import (
    MANAUS_TZ,
    MAX_IMAGE_BYTES,
    MAX_IMAGE_DIMENSION,
    MAX_IMAGE_PIXELS,
)


def esc(value: object) -> str:
    """Escapa texto para inserção segura em HTML e atributos."""
    return html.escape(str(value if value is not None else ""), quote=True)


def normalize_text(text: str) -> str:
    """Remove acentos e normaliza para busca tolerante (ex.: 'eletrica' -> 'eletrica')."""
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return stripped.casefold().strip()


def now_iso() -> str:
    """Timestamp UTC ISO-8601 para armazenamento consistente no banco."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def format_manaus_time(iso_str: str) -> str:
    """Converte timestamp ISO UTC para horário local de Manaus (dd/mm HH:MM)."""
    try:
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        local_dt = dt.astimezone(MANAUS_TZ)
        today = datetime.now(MANAUS_TZ).date()
        if local_dt.date() == today:
            return local_dt.strftime("Hoje, %H:%M")
        return local_dt.strftime("%d/%m às %H:%M")
    except (ValueError, TypeError):
        return ""


def format_manaus_date(iso_str: str) -> str:
    """Converte timestamp ISO UTC para data legível em Manaus (dd/mm/aaaa)."""
    try:
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(MANAUS_TZ).strftime("%d/%m/%Y")
    except (ValueError, TypeError):
        return ""


def clean_whatsapp(phone: str) -> str:
    """Extrai apenas dígitos válidos de telefone brasileiro (DDD + número)."""
    digits = re.sub(r"\D+", "", phone or "")
    if digits.startswith("55") and len(digits) in (12, 13):
        digits = digits[2:]
    if len(digits) in (10, 11):
        return digits
    return ""


def format_phone_display(digits: str) -> str:
    """Formata telefone brasileiro para exibição amigável."""
    if len(digits) == 11:
        return f"({digits[:2]}) {digits[2:7]}-{digits[7:]}"
    if len(digits) == 10:
        return f"({digits[:2]}) {digits[2:6]}-{digits[6:]}"
    return digits


def whatsapp_link(digits: str, pro_name: str, category: str) -> str:
    """Monta link oficial do WhatsApp com mensagem inicial pronta."""
    if not digits:
        return ""
    msg = (
        f"Olá, {pro_name}! Encontrei seu perfil de {category} no OndeTem "
        f"e gostaria de solicitar um orçamento."
    )
    return f"https://wa.me/55{digits}?text={quote(msg)}"


def password_hash(password: str) -> str:
    """Gera hash PBKDF2-HMAC-SHA256 com salt aleatório de 16 bytes."""
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 260_000)
    return salt.hex() + ":" + digest.hex()


def password_matches(password: str, stored: str) -> bool:
    """Valida senha em tempo constante (suporta 260k e 200k legado)."""
    try:
        salt_hex, expected_hex = stored.split(":", 1)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(expected_hex)
        for iterations in (260_000, 200_000):
            digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
            if hmac.compare_digest(digest, expected):
                return True
        return False
    except (ValueError, TypeError):
        return False


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def safe_destination(value: str, fallback: str = "/") -> str:
    """Permite apenas redirecionamentos relativos locais (proteção contra Open Redirect)."""
    if not isinstance(value, str) or not value:
        return fallback
    decoded = unquote(value)
    for candidate in (value, decoded):
        if (
            not candidate.startswith("/")
            or candidate.startswith("//")
            or "\\" in candidate
            or any(ord(ch) < 32 or ord(ch) == 127 for ch in candidate)
        ):
            return fallback
    try:
        parts = urlsplit(value)
    except ValueError:
        return fallback
    if parts.scheme or parts.netloc:
        return fallback
    return quote(value, safe="/%?=&#+:;,@!$'()*-._~")


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distância aproximada (Haversine) em quilômetros."""
    radius = 6371.0
    r_lat1, r_lat2 = math.radians(lat1), math.radians(lat2)
    dlat = r_lat2 - r_lat1
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(r_lat1) * math.cos(r_lat2) * math.sin(dlon / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def sanitize_image(picture: bytes) -> tuple[bytes, str] | tuple[None, str]:
    """Valida, corrige orientação EXIF, remove metadados e reencoda a imagem com segurança."""
    if not picture or len(picture) > MAX_IMAGE_BYTES:
        return None, ""
    allowed = {"PNG": ("PNG", ".png"), "JPEG": ("JPEG", ".jpg"), "WEBP": ("WEBP", ".webp")}
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(picture)) as img:
                if img.format not in allowed:
                    return None, ""
                if img.width * img.height > MAX_IMAGE_PIXELS:
                    return None, ""
                img.verify()
            with Image.open(io.BytesIO(picture)) as img:
                pil_fmt, ext = allowed[img.format]
                img = ImageOps.exif_transpose(img)
                img.thumbnail((MAX_IMAGE_DIMENSION, MAX_IMAGE_DIMENSION), Image.Resampling.LANCZOS)
                out = io.BytesIO()
                if pil_fmt == "JPEG":
                    if img.mode not in ("RGB", "L"):
                        img = img.convert("RGB")
                    img.save(out, format="JPEG", quality=85, optimize=True)
                elif pil_fmt == "WEBP":
                    if img.mode not in ("RGB", "RGBA"):
                        img = img.convert("RGB")
                    img.save(out, format="WEBP", quality=85)
                else:
                    img.save(out, format="PNG", optimize=True)
                return out.getvalue(), ext
    except (
        UnidentifiedImageError,
        OSError,
        ValueError,
        SyntaxError,
        EOFError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ):
        return None, ""


class RateLimiter:
    """Limitador de taxa em memória por janela deslizante para proteger login e cadastro."""

    def __init__(self, max_requests: int = 12, window_seconds: int = 60) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        cutoff = now - self.window_seconds
        with self._lock:
            bucket = self._hits[key]
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= self.max_requests:
                return False
            bucket.append(now)
            return True


AUTH_LIMITER = RateLimiter(max_requests=15, window_seconds=60)


def sanitize_avatar(picture: bytes) -> tuple[bytes, str] | tuple[None, str]:
    """Valida, recorta em quadrado 512x512 e remove metadados EXIF da foto de perfil."""
    cleaned, ext = sanitize_image(picture)
    if not cleaned:
        return None, ""
    try:
        with Image.open(io.BytesIO(cleaned)) as img:
            img = ImageOps.fit(img, (512, 512), method=Image.Resampling.LANCZOS)
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            out = io.BytesIO()
            img.save(out, format="JPEG", quality=86, optimize=True)
            return out.getvalue(), ".jpg"
    except Exception:
        return None, ""
