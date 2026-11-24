"""Configurações centrais, variáveis de ambiente, categorias e bairros de Manaus."""

from __future__ import annotations

import os
from datetime import timedelta, timezone
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

ROOT = Path(__file__).resolve().parent.parent
if load_dotenv is not None:
    load_dotenv(ROOT / ".env")

STATIC_DIR = ROOT / "static"
UPLOADS_DIR = STATIC_DIR / "uploads"
DB_PATH = ROOT / "instance" / "ondetem.db"

# Banco em nuvem (PostgreSQL no Render/Neon/Supabase). Se vazio, usa SQLite local.
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = "postgresql://" + DATABASE_URL[len("postgres://") :]

HOST = os.environ.get("ONDETEM_HOST", "0.0.0.0" if DATABASE_URL else "127.0.0.1")
_raw_port = os.environ.get("PORT") or os.environ.get("ONDETEM_PORT") or "8001"
try:
    PORT = int(_raw_port)
    if not 1 <= PORT <= 65535:
        raise ValueError
except ValueError:
    raise SystemExit("PORT/ONDETEM_PORT deve ser um número entre 1 e 65535.")

READ_ONLY_DEMO = os.environ.get("ONDETEM_READONLY", "0").strip().lower() in ("1", "true", "yes")
USE_SECURE_COOKIE = os.environ.get("ONDETEM_HTTPS", "0").strip().lower() in ("1", "true", "yes")

SESSION_AGE = 60 * 60 * 24 * 7  # 7 dias
MAX_POST_BYTES = 5 * 1024 * 1024
MAX_IMAGE_BYTES = 3 * 1024 * 1024
MAX_IMAGE_PIXELS = 20_000_000
MAX_IMAGE_DIMENSION = 1600
MAX_PORTFOLIO_ITEMS = 12

# Fuso horário de Manaus (AMT = UTC-4)
MANAUS_TZ = timezone(timedelta(hours=-4))

# Categorias de serviços com identificador de ícone SVG
CATEGORY_GROUPS: list[str] = [
    "Casa & Reparos",
    "Confeitaria & Eventos",
    "Tech & Negócios",
    "Cuidados & Aulas",
]

CATEGORIES: dict[str, dict[str, str]] = {
    # Casa & Reparos
    "Eletricista": {"icon": "bolt", "short": "Elétrica residencial e predial", "group": "Casa & Reparos"},
    "Encanador": {"icon": "droplet", "short": "Hidráulica e vazamentos", "group": "Casa & Reparos"},
    "Ar-condicionado": {"icon": "snowflake", "short": "Instalação e higienização", "group": "Casa & Reparos"},
    "Diarista / Limpeza": {"icon": "sparkles", "short": "Limpeza residencial e pós-obra", "group": "Casa & Reparos"},
    "Pintor": {"icon": "brush", "short": "Pintura interna e externa", "group": "Casa & Reparos"},
    "Montador de móveis": {"icon": "wrench", "short": "Montagem e ajustes", "group": "Casa & Reparos"},
    "Pedreiro / Reformas": {"icon": "hammer", "short": "Alvenaria, pisos e reparos", "group": "Casa & Reparos"},
    "Chaveiro": {"icon": "key", "short": "Aberturas e cópias 24h", "group": "Casa & Reparos"},
    "Jardineiro / Paisagismo": {"icon": "leaf", "short": "Poda, grama e jardins", "group": "Casa & Reparos"},
    "Frete / Mudanças": {"icon": "truck", "short": "Carreto, entregas e mudanças", "group": "Casa & Reparos"},
    # Confeitaria & Eventos
    "Confeiteira / Bolos & Doces": {"icon": "cake", "short": "Bolos decorados, docinhos e tortas", "group": "Confeitaria & Eventos"},
    "Salgados & Buffet": {"icon": "utensils", "short": "Salgadinhos, kits festa e buffet", "group": "Confeitaria & Eventos"},
    "Marmitas & Comida Caseira": {"icon": "chef", "short": "Refeições, fit e encomendas", "group": "Confeitaria & Eventos"},
    "Decoração de Festas": {"icon": "party", "short": "Painéis, balões e mesas temáticas", "group": "Confeitaria & Eventos"},
    "Músico / Eventos": {"icon": "music", "short": "Voz e violão, DJ, som e festas", "group": "Confeitaria & Eventos"},
    "Fotógrafo / Vídeo": {"icon": "camera", "short": "Ensaios, eventos e redes", "group": "Confeitaria & Eventos"},
    # Tech & Negócios
    "Mecânico / Auto": {"icon": "car", "short": "Revisão, freios e socorro", "group": "Tech & Negócios"},
    "Técnico de TI / Informática": {"icon": "laptop", "short": "PCs, redes, formatação e suporte", "group": "Tech & Negócios"},
    "Contador / MEI": {"icon": "calculator", "short": "Imposto de renda, MEI e fiscal", "group": "Tech & Negócios"},
    "Design / Social Media": {"icon": "palette", "short": "Artes, logos, sites e gestão", "group": "Tech & Negócios"},
    # Cuidados & Aulas
    "Beleza / Cabeleireiro": {"icon": "scissors", "short": "Corte, manicure e maquiagem", "group": "Cuidados & Aulas"},
    "Personal Trainer": {"icon": "dumbbell", "short": "Treino funcional e saúde", "group": "Cuidados & Aulas"},
    "Professor Particular": {"icon": "book", "short": "Reforço, inglês e concursos", "group": "Cuidados & Aulas"},
    "Cuidador / Babá": {"icon": "users", "short": "Cuidado de idosos e crianças", "group": "Cuidados & Aulas"},
}

# Coordenadas aproximadas dos principais bairros de Manaus (AM)
NEIGHBORHOODS: dict[str, tuple[float, float]] = {
    "Adrianópolis": (-3.0990, -60.0140),
    "Aleixo": (-3.0940, -59.9860),
    "Alvorada": (-3.0805, -60.0470),
    "Cachoeirinha": (-3.1285, -60.0085),
    "Centro": (-3.1325, -60.0235),
    "Chapada": (-3.0985, -60.0265),
    "Cidade Nova": (-3.0440, -59.9820),
    "Compensa": (-3.1030, -60.0560),
    "Coroado": (-3.0935, -59.9720),
    "Dom Pedro": (-3.0870, -60.0385),
    "Flores": (-3.0680, -60.0070),
    "Japiim": (-3.1245, -59.9895),
    "Lírio do Vale": (-3.0760, -60.0620),
    "Nossa Senhora das Graças": (-3.1045, -60.0225),
    "Nova Cidade": (-3.0255, -59.9875),
    "Parque Dez": (-3.0855, -60.0095),
    "Petrópolis": (-3.1165, -59.9960),
    "Planalto": (-3.0785, -60.0410),
    "Ponta Negra": (-3.0675, -60.1015),
    "São Jorge": (-3.1095, -60.0390),
    "São José Operário": (-3.0695, -59.9465),
    "Tarumã": (-3.0285, -60.0490),
    "Vieiralves": (-3.1060, -60.0210),
}

RESPONSE_TIMES = [
    "Responde em até 15 min",
    "Responde em até 30 min",
    "Responde em até 1 hora",
    "Responde no mesmo dia",
]

# E-mails com acesso ao painel /admin (separados por vírgula no .env ou Render)
ADMIN_EMAILS: set[str] = {
    e.strip().lower()
    for e in os.environ.get("ADMIN_EMAILS", "").split(",")
    if e.strip()
}

# URL pública oficial (atualize quando conectar domínio próprio, ex.: https://ondetem.me)
APP_BASE_URL = os.environ.get("APP_BASE_URL", "https://ondetem-manaus.onrender.com").rstrip("/")
