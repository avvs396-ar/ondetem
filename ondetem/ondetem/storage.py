"""Camada de armazenamento de imagens: Cloudinary (nuvem permanente) com fallback local."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from ondetem.config import STATIC_DIR, UPLOADS_DIR


def _cloudinary_creds() -> tuple[str, str, str]:
    """Lê credenciais do Cloudinary (CLOUDINARY_URL ou 3 variáveis separadas)."""
    url = os.environ.get("CLOUDINARY_URL", "").strip()
    if url.startswith("cloudinary://"):
        parsed = urllib.parse.urlparse(url)
        return (parsed.hostname or "", parsed.username or "", parsed.password or "")
    return (
        os.environ.get("CLOUDINARY_CLOUD_NAME", "").strip(),
        os.environ.get("CLOUDINARY_API_KEY", "").strip(),
        os.environ.get("CLOUDINARY_API_SECRET", "").strip(),
    )


def storage_backend_name() -> str:
    cloud, key, secret = _cloudinary_creds()
    return "cloudinary" if (cloud and key and secret) else "local"


def build_cloudinary_signature(params: dict[str, str], api_secret: str) -> str:
    """Gera assinatura SHA-1 oficial exigida pela API assinada do Cloudinary."""
    to_sign = "&".join(f"{k}={params[k]}" for k in sorted(params) if params[k] != "")
    return hashlib.sha1((to_sign + api_secret).encode("utf-8")).hexdigest()


def _multipart_body(fields: dict[str, str], file_field: str, filename: str, content: bytes, mime: str) -> tuple[bytes, str]:
    boundary = "----OndeTemBoundary" + secrets.token_hex(12)
    chunks: list[bytes] = []
    for k, v in fields.items():
        chunks.append(f"--{boundary}\r\n".encode())
        chunks.append(f'Content-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    chunks.append(f"--{boundary}\r\n".encode())
    chunks.append(
        f'Content-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\n'
        f"Content-Type: {mime}\r\n\r\n".encode()
    )
    chunks.append(content)
    chunks.append(f"\r\n--{boundary}--\r\n".encode())
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def upload_image(clean_bytes: bytes, ext: str, folder: str = "ondetem/portfolio") -> str:
    """Salva imagem sanitizada no Cloudinary (se configurado) ou no disco local."""
    cloud, api_key, api_secret = _cloudinary_creds()
    if cloud and api_key and api_secret:
        timestamp = str(int(time.time()))
        public_id = f"{folder}/{secrets.token_hex(12)}"
        sign_params = {"public_id": public_id, "timestamp": timestamp}
        signature = build_cloudinary_signature(sign_params, api_secret)

        mime_map = {".jpg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
        body, content_type = _multipart_body(
            fields={
                "api_key": api_key,
                "timestamp": timestamp,
                "public_id": public_id,
                "signature": signature,
            },
            file_field="file",
            filename="upload" + ext,
            content=clean_bytes,
            mime=mime_map.get(ext, "application/octet-stream"),
        )
        endpoint = f"https://api.cloudinary.com/v1_1/{cloud}/image/upload"
        req = urllib.request.Request(endpoint, data=body, headers={"Content-Type": content_type}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                secure_url = str(data.get("secure_url", ""))
                if secure_url.startswith("https://res.cloudinary.com/"):
                    return secure_url.replace("/upload/", "/upload/f_auto,q_auto/", 1)
        except (urllib.error.URLError, TimeoutError, ValueError, KeyError):
            # Fallback seguro caso haja instabilidade momentânea
            pass

    filename = secrets.token_hex(16) + ext
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    (UPLOADS_DIR / filename).write_bytes(clean_bytes)
    return "uploads/" + filename


def resolve_image_url(stored_path: str) -> str:
    """Retorna URL pronta para <img src> (suporta URLs Cloudinary https:// e arquivos locais)."""
    if not stored_path:
        return ""
    if stored_path.startswith(("https://", "http://", "/")):
        return stored_path
    return "/static/" + stored_path


def delete_stored_image(stored_path: str) -> None:
    """Remove arquivo local quando aplicável (não quebra em URLs externas)."""
    if not stored_path or stored_path.startswith(("https://", "http://")):
        return
    if stored_path.startswith("uploads/"):
        fp = (STATIC_DIR / stored_path).resolve()
        if fp.is_relative_to(UPLOADS_DIR.resolve()) and fp.is_file():
            fp.unlink(missing_ok=True)
