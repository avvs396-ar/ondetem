"""Camada de banco de dados dual: PostgreSQL (produção/nuvem) + SQLite (local)."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any

from ondetem.config import DATABASE_URL, DB_PATH, NEIGHBORHOODS, UPLOADS_DIR
from ondetem.security import now_iso, password_hash


def translate_sql_for_postgres(sql: str) -> str:
    """Converte placeholders '?' do SQLite para '%s' do PostgreSQL."""
    return sql.replace("?", "%s")


class DBError(Exception):
    """Erro genérico de integridade/banco independente do driver."""


class IntegrityConflictError(DBError):
    """Violação de chave única (ex.: e-mail já cadastrado)."""


class DBSession:
    """Wrapper unificado para executar SQL em SQLite ou PostgreSQL sem duplicar código."""

    def __init__(self, conn: Any, is_postgres: bool) -> None:
        self._conn = conn
        self.is_postgres = is_postgres

    @property
    def engine_name(self) -> str:
        return "postgresql" if self.is_postgres else "sqlite"

    def _prepare(self, sql: str) -> str:
        return translate_sql_for_postgres(sql) if self.is_postgres else sql

    def execute(self, sql: str, params: tuple | list = ()):
        query = self._prepare(sql)
        try:
            cur = self._conn.cursor()
            cur.execute(query, params)
            return cur
        except sqlite3.IntegrityError as exc:
            raise IntegrityConflictError(str(exc)) from exc
        except Exception as exc:
            if exc.__class__.__name__ in ("UniqueViolation", "IntegrityError"):
                raise IntegrityConflictError(str(exc)) from exc
            raise

    def fetchone(self, sql: str, params: tuple | list = ()) -> dict[str, Any] | None:
        cur = self.execute(sql, params)
        row = cur.fetchone()
        return dict(row) if row is not None else None

    def fetchall(self, sql: str, params: tuple | list = ()) -> list[dict[str, Any]]:
        cur = self.execute(sql, params)
        return [dict(row) for row in cur.fetchall()]

    def scalar(self, sql: str, params: tuple | list = (), default: Any = 0) -> Any:
        cur = self.execute(sql, params)
        row = cur.fetchone()
        if row is None:
            return default
        if isinstance(row, dict):
            return next(iter(row.values()))
        return row[0]

    def insert_returning_id(self, sql: str, params: tuple | list = ()) -> int:
        if self.is_postgres:
            query = self._prepare(sql).rstrip().rstrip(";") + " RETURNING id"
            cur = self.execute(query, params)
            row = cur.fetchone()
            return int(row["id"] if isinstance(row, dict) else row[0])
        cur = self.execute(sql, params)
        return int(cur.lastrowid)

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "DBSession":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type is None:
            self.commit()
        else:
            self.rollback()
        self.close()


def _resolve_database_url(database_url: str | None = None) -> str:
    if database_url is not None:
        url = database_url.strip()
    else:
        url = os.environ.get("DATABASE_URL", DATABASE_URL).strip()
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    return url


def get_db(db_path: Path | None = None, database_url: str | None = None) -> DBSession:
    """Abre sessão no PostgreSQL (se DATABASE_URL estiver definida) ou SQLite local."""
    url = _resolve_database_url(database_url)
    if url and db_path is None:
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:  # pragma: no cover
            raise SystemExit(
                "DATABASE_URL configurada para PostgreSQL, mas 'psycopg' não está instalado. "
                "Rode: pip install 'psycopg[binary]'"
            ) from exc
        conn = psycopg.connect(url, row_factory=dict_row)
        return DBSession(conn, is_postgres=True)

    target = db_path or DB_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return DBSession(conn, is_postgres=False)


POSTGRES_SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        name TEXT NOT NULL,
        email TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL CHECK(role IN ('cliente', 'profissional')),
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS professionals (
        user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
        category TEXT NOT NULL,
        neighborhood TEXT NOT NULL,
        bio TEXT NOT NULL DEFAULT '',
        experience TEXT NOT NULL DEFAULT '',
        price_text TEXT NOT NULL DEFAULT '',
        whatsapp TEXT NOT NULL DEFAULT '',
        response_time TEXT NOT NULL DEFAULT 'Responde em até 1 hora',
        verified INTEGER NOT NULL DEFAULT 0,
        available INTEGER NOT NULL DEFAULT 1,
        lat DOUBLE PRECISION,
        lon DOUBLE PRECISION
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS works (
        id SERIAL PRIMARY KEY,
        professional_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        image TEXT NOT NULL,
        caption TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT ''
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS reviews (
        id SERIAL PRIMARY KEY,
        client_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        professional_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        rating INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5),
        comment TEXT NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE(client_id, professional_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS conversations (
        id SERIAL PRIMARY KEY,
        client_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        professional_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        created_at TEXT NOT NULL,
        UNIQUE(client_id, professional_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS messages (
        id SERIAL PRIMARY KEY,
        conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
        sender_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        body TEXT NOT NULL,
        created_at TEXT NOT NULL,
        read_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sessions (
        token_hash TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        csrf TEXT NOT NULL,
        expires_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_prof_cat_neigh ON professionals(category, neighborhood)",
    "CREATE INDEX IF NOT EXISTS idx_reviews_pro ON reviews(professional_id)",
    "CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id, id)",
    "CREATE INDEX IF NOT EXISTS idx_sessions_exp ON sessions(expires_at)",
]

SQLITE_SCHEMA = [stmt.replace("SERIAL PRIMARY KEY", "INTEGER PRIMARY KEY").replace("DOUBLE PRECISION", "REAL") for stmt in POSTGRES_SCHEMA]


def init_database(db_path: Path | None = None, database_url: str | None = None) -> None:
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    with get_db(db_path=db_path, database_url=database_url) as db:
        statements = POSTGRES_SCHEMA if db.is_postgres else SQLITE_SCHEMA
        for stmt in statements:
            db.execute(stmt)
        if db.fetchone("SELECT 1 AS ok FROM users LIMIT 1"):
            return
        _seed_demo_data(db)


def _seed_demo_data(db: DBSession) -> None:
    """Popula dados realistas de Manaus para demonstração completa."""
    demo_clients = [
        ("Cliente Demonstração", "cliente@ondetem.local"),
        ("Fernanda Souza", "fernanda.demo@ondetem.local"),
        ("Ricardo Mendes", "ricardo.demo@ondetem.local"),
    ]
    client_ids: list[int] = []
    for name, email in demo_clients:
        uid = db.insert_returning_id(
            "INSERT INTO users (name, email, password_hash, role, created_at) VALUES (?, ?, ?, 'cliente', ?)",
            (name, email, password_hash("Demo123!"), now_iso()),
        )
        client_ids.append(uid)

    pros = [
        {
            "name": "Carlos Silva",
            "email": "carlos@ondetem.local",
            "category": "Eletricista",
            "neighborhood": "Ponta Negra",
            "bio": "Instalações elétricas residenciais, troca de disjuntores, chuveiros, tomadas 220V e revisão de quadros seguindo a NBR 5410.",
            "experience": "8 anos de experiência em elétrica residencial e predial. Técnico em Eletrotécnica com certificação NR-10.",
            "price": "Visita técnica a partir de R$ 80",
            "whatsapp": "92991001001",
            "response_time": "Responde em até 15 min",
            "verified": 1,
            "available": 1,
            "work": ("work-eletrica.svg", "Reorganização completa de quadro de distribuição residencial"),
            "reviews": [
                (0, 5, "Muito pontual, explicou o problema no disjuntor e deixou tudo organizado e testado."),
                (1, 5, "Instalou 4 pontos de tomada e luminárias na sala sem sujeira. Recomendo demais!"),
            ],
        },
        {
            "name": "Marina Costa",
            "email": "marina@ondetem.local",
            "category": "Ar-condicionado",
            "neighborhood": "Parque Dez",
            "bio": "Limpeza preventiva com bolsa coletora, recarga de gás, instalação de splits inverter e diagnóstico de vazamento de água.",
            "experience": "7 anos atuando com climatização residencial e comercial em Manaus. Especialista em sistemas Inverter.",
            "price": "Higienização a partir de R$ 130",
            "whatsapp": "92991002002",
            "response_time": "Responde em até 30 min",
            "verified": 1,
            "available": 1,
            "work": ("work-ar.svg", "Higienização completa e teste de pressão em split 12.000 BTUs"),
            "reviews": [
                (0, 5, "Excelente atendimento! O ar voltou a gelar muito rápido e não molhou nada no quarto."),
                (2, 5, "Preço justo e serviço limpo. Resolveu um vazamento que outro técnico não achava."),
            ],
        },
        {
            "name": "Bruno Lima",
            "email": "bruno@ondetem.local",
            "category": "Encanador",
            "neighborhood": "Adrianópolis",
            "bio": "Caça-vazamentos sem quebra-quebra, troca de registros, torneiras, válvulas Hydra, desentupimento e manutenção de caixa d'água.",
            "experience": "6 anos atendendo residências e condomínios na Zona Centro-Sul de Manaus.",
            "price": "Atendimento a partir de R$ 70",
            "whatsapp": "92991003003",
            "response_time": "Responde em até 30 min",
            "verified": 1,
            "available": 1,
            "work": ("work-hidraulica.svg", "Substituição de tubulação e instalação de misturador"),
            "reviews": [
                (1, 5, "Chegou no horário combinado e resolveu o vazamento embaixo da pia em menos de 1 hora."),
                (2, 4, "Bom serviço e valor transparente antes de começar."),
            ],
        },
        {
            "name": "Ana Ferreira",
            "email": "ana@ondetem.local",
            "category": "Pintor",
            "neighborhood": "Vieiralves",
            "bio": "Pintura residencial de alto acabamento, massa corrida, tratamento de umidade, textura e proteção completa de pisos e móveis.",
            "experience": "5 anos em pintura de apartamentos, casas e salas comerciais com foco em acabamento limpo.",
            "price": "Orçamento gratuito após avaliação",
            "whatsapp": "92991004004",
            "response_time": "Responde em até 1 hora",
            "verified": 1,
            "available": 1,
            "work": ("work-pintura.svg", "Pintura acrílica fosca e acabamento em sala de estar"),
            "reviews": [
                (0, 5, "Capricho impressionante nos recortes e entregou o apartamento impecável."),
            ],
        },
        {
            "name": "João Pereira",
            "email": "joao@ondetem.local",
            "category": "Montador de móveis",
            "neighborhood": "Cidade Nova",
            "bio": "Montagem e desmontagem de guarda-roupas, cozinhas moduladas, painéis de TV com suporte e regulagem de dobradiças.",
            "experience": "4 anos trabalhando com móveis convencionais, modulados e mudanças residenciais.",
            "price": "Montagem a partir de R$ 90",
            "whatsapp": "92991005005",
            "response_time": "Responde em até 1 hora",
            "verified": 0,
            "available": 1,
            "work": ("work-moveis.svg", "Montagem de guarda-roupa de 6 portas e painel suspenso"),
            "reviews": [
                (2, 5, "Montou meu guarda-roupa e nivelou todas as portas perfeitamente."),
            ],
        },
        {
            "name": "Roberto Nascimento",
            "email": "roberto@ondetem.local",
            "category": "Chaveiro",
            "neighborhood": "Centro",
            "bio": "Abertura residencial e automotiva sem danos, troca de segredo, instalação de fechaduras digitais e cópias codificadas.",
            "experience": "10 anos como chaveiro autônomo com atendimento rápido em toda Manaus.",
            "price": "Abertura a partir de R$ 60",
            "whatsapp": "92991006006",
            "response_time": "Responde em até 15 min",
            "verified": 1,
            "available": 1,
            "work": ("work-moveis.svg", "Instalação de fechadura eletrônica em porta de madeira"),
            "reviews": [
                (1, 5, "Salvou meu dia! Chegou em 20 minutos e instalou a fechadura digital sem marcas na porta."),
            ],
        },
        {
            "name": "Patrícia Almeida",
            "email": "patricia@ondetem.local",
            "category": "Diarista / Limpeza",
            "neighborhood": "Flores",
            "bio": "Limpeza residencial detalhada, organização de ambientes e limpeza pós-obra para casas e apartamentos.",
            "experience": "6 anos com referências verificadas em condomínios de Flores e Parque Dez.",
            "price": "Diária a partir de R$ 150",
            "whatsapp": "92991007007",
            "response_time": "Responde no mesmo dia",
            "verified": 1,
            "available": 1,
            "work": ("work-pintura.svg", "Higienização e organização completa pós-reforma"),
            "reviews": [
                (0, 5, "Super confiável, cuidadosa com os móveis e deixou a casa brilhando."),
            ],
        },
        {
            "name": "Eduardo Santos",
            "email": "eduardo@ondetem.local",
            "category": "Pedreiro / Reformas",
            "neighborhood": "Aleixo",
            "bio": "Assentamento de porcelanato, pequenos reparos em alvenaria, reboco, impermeabilização de lajes e instalação de bancadas.",
            "experience": "12 anos em reformas residenciais com compromisso de prazo e limpeza da obra.",
            "price": "Orçamento sob medida",
            "whatsapp": "92991008008",
            "response_time": "Responde no mesmo dia",
            "verified": 0,
            "available": 0,
            "work": ("work-hidraulica.svg", "Revestimento cerâmico e acabamento de banheiro"),
            "reviews": [
                (2, 4, "Serviço muito bem feito no revestimento da cozinha."),
            ],
        },
    ]

    for p in pros:
        uid = db.insert_returning_id(
            "INSERT INTO users (name, email, password_hash, role, created_at) VALUES (?, ?, ?, 'profissional', ?)",
            (p["name"], p["email"], password_hash("Demo123!"), now_iso()),
        )
        lat, lon = NEIGHBORHOODS[p["neighborhood"]]
        db.execute(
            """
            INSERT INTO professionals
            (user_id, category, neighborhood, bio, experience, price_text, whatsapp, response_time, verified, available, lat, lon)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                uid,
                p["category"],
                p["neighborhood"],
                p["bio"],
                p["experience"],
                p["price"],
                p["whatsapp"],
                p["response_time"],
                p["verified"],
                p["available"],
                lat,
                lon,
            ),
        )
        db.execute(
            "INSERT INTO works (professional_id, image, caption, created_at) VALUES (?, ?, ?, ?)",
            (uid, p["work"][0], p["work"][1], now_iso()),
        )
        for c_idx, rating, comment in p["reviews"]:
            db.execute(
                "INSERT INTO reviews (client_id, professional_id, rating, comment, created_at) VALUES (?, ?, ?, ?, ?)",
                (client_ids[c_idx], uid, rating, comment, now_iso()),
            )
