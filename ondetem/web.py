"""Aplicação web de produção do OndeTem em FastAPI + PostgreSQL/SQLite."""

from __future__ import annotations

import hmac
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from ondetem import __version__
from ondetem.config import (
    CATEGORIES,
    MAX_PORTFOLIO_ITEMS,
    NEIGHBORHOODS,
    READ_ONLY_DEMO,
    RESPONSE_TIMES,
    SESSION_AGE,
    STATIC_DIR,
    UPLOADS_DIR,
    USE_SECURE_COOKIE,
)
from ondetem.db import DBSession, IntegrityConflictError, get_db, init_database
from ondetem.security import (
    AUTH_LIMITER,
    clean_whatsapp,
    distance_km,
    normalize_text,
    now_iso,
    password_hash,
    password_matches,
    safe_destination,
    sanitize_image,
    token_hash,
)
from ondetem.views import (
    auth_view,
    chat_view,
    conversations_view,
    dashboard_view,
    home_view,
    layout_page,
    profile_view,
    search_view,
)


def create_app(db_path: Path | None = None, database_url: str | None = None) -> FastAPI:
    """Factory da aplicação FastAPI (facilita testes isolados e deploy em nuvem)."""

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        init_database(db_path=db_path, database_url=database_url)
        yield

    app = FastAPI(
        title="OndeTem Manaus API & Web",
        version=__version__,
        description="Plataforma conectando moradores de Manaus a profissionais autônomos.",
        lifespan=lifespan,
    )

    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    _initialized = {'done': False}

    def ensure_db_ready() -> None:
        if not _initialized['done']:
            init_database(db_path=db_path, database_url=database_url)
            _initialized['done'] = True

    def open_db() -> DBSession:
        ensure_db_ready()
        return get_db(db_path=db_path, database_url=database_url)

    def current_user(db: DBSession, request: Request) -> dict[str, Any] | None:
        token = request.cookies.get("session", "")
        if not token:
            return None
        return db.fetchone(
            """SELECT u.id, u.name, u.role, s.csrf
               FROM sessions s JOIN users u ON u.id = s.user_id
               WHERE s.token_hash = ? AND s.expires_at > ?""",
            (token_hash(token), now_iso()),
        )

    def unread_count(db: DBSession, user: dict | None) -> int:
        if not user:
            return 0
        return int(
            db.scalar(
                """SELECT COUNT(*) FROM messages m
                   JOIN conversations c ON c.id = m.conversation_id
                   WHERE (c.client_id = ? OR c.professional_id = ?)
                     AND m.sender_id <> ? AND m.read_at IS NULL""",
                (user["id"], user["id"], user["id"]),
                default=0,
            )
        )

    def query_professionals(db: DBSession, limit: int | None = None) -> list[dict[str, Any]]:
        sql = """
            SELECT p.*, u.name,
                (SELECT AVG(rating) FROM reviews r WHERE r.professional_id = p.user_id) AS rating,
                (SELECT COUNT(*) FROM reviews r WHERE r.professional_id = p.user_id) AS review_count
            FROM professionals p
            JOIN users u ON u.id = p.user_id
            ORDER BY p.available DESC, p.verified DESC, rating DESC, u.name ASC
        """
        if limit is not None:
            return db.fetchall(sql + " LIMIT ?", (int(limit),))
        return db.fetchall(sql)

    def get_pro(db: DBSession, uid: int) -> dict[str, Any] | None:
        return db.fetchone(
            """SELECT p.*, u.name,
                (SELECT AVG(rating) FROM reviews WHERE professional_id = p.user_id) AS rating,
                (SELECT COUNT(*) FROM reviews WHERE professional_id = p.user_id) AS review_count
               FROM professionals p JOIN users u ON u.id = p.user_id
               WHERE p.user_id = ?""",
            (uid,),
        )

    def query_stats(db: DBSession) -> dict[str, Any]:
        pros = int(db.scalar("SELECT COUNT(*) FROM professionals", default=0))
        reviews = int(db.scalar("SELECT COUNT(*) FROM reviews", default=0))
        avg_rating = float(db.scalar("SELECT COALESCE(AVG(rating), 5.0) FROM reviews", default=5.0) or 5.0)
        return {
            "pros": pros,
            "reviews": reviews,
            "avg_rating": avg_rating,
            "neighborhoods": len(NEIGHBORHOODS),
        }

    def check_csrf(user: dict | None, csrf: str) -> bool:
        if not user:
            return False
        return hmac.compare_digest(csrf.encode("utf-8"), str(user["csrf"]).encode("utf-8"))

    def login_redirect(db: DBSession, uid: int, destination: str) -> RedirectResponse:
        token = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(32)
        expiry = (datetime.now(timezone.utc) + timedelta(seconds=SESSION_AGE)).isoformat(timespec="seconds")
        db.execute("DELETE FROM sessions WHERE expires_at <= ?", (now_iso(),))
        db.execute(
            "INSERT INTO sessions (token_hash, user_id, csrf, expires_at) VALUES (?, ?, ?, ?)",
            (token_hash(token), uid, csrf, expiry),
        )
        resp = RedirectResponse(url=safe_destination(destination), status_code=303)
        resp.set_cookie(
            key="session",
            value=token,
            max_age=SESSION_AGE,
            path="/",
            httponly=True,
            samesite="lax",
            secure=USE_SECURE_COOKIE,
        )
        return resp

    def filter_pros(db: DBSession, params: dict[str, str]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        q = params.get("q", "").strip()[:80]
        q_norm = normalize_text(q)
        category = params.get("categoria", "")
        neighborhood = params.get("bairro", "")
        sort_by = params.get("ordenar", "relevancia")
        only_avail = params.get("disponivel", "") == "1"
        min_rating_str = params.get("nota", "")
        saved_mode = params.get("salvos", "") == "1"

        min_rating = 0.0
        try:
            if min_rating_str:
                min_rating = float(min_rating_str)
        except ValueError:
            min_rating_str = ""

        lat = lon = None
        try:
            if params.get("lat") and params.get("lon"):
                lat, lon = float(params["lat"]), float(params["lon"])
                if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                    lat = lon = None
        except ValueError:
            lat = lon = None

        found: list[dict[str, Any]] = []
        for pro in query_professionals(db):
            if q_norm:
                haystack = normalize_text(
                    f"{pro['name']} {pro['category']} {pro['neighborhood']} {pro['bio']} {pro['experience']}"
                )
                if not all(term in haystack for term in q_norm.split()):
                    continue
            if category in CATEGORIES and pro["category"] != category:
                continue
            if neighborhood in NEIGHBORHOODS and pro["neighborhood"] != neighborhood:
                continue
            if only_avail and not pro["available"]:
                continue
            if min_rating > 0 and (pro["rating"] is None or float(pro["rating"]) < min_rating):
                continue

            item = dict(pro)
            if lat is not None and pro["lat"] is not None:
                item["distance"] = distance_km(lat, lon, float(pro["lat"]), float(pro["lon"]))
            found.append(item)

        if lat is not None and sort_by in ("relevancia", "proximidade"):
            found.sort(key=lambda p: p.get("distance", 100_000))
            sort_by = "proximidade"
        elif sort_by == "nota":
            found.sort(key=lambda p: (-(p["rating"] or 0), -(p["review_count"] or 0), p["name"]))
        elif sort_by == "avaliacoes":
            found.sort(key=lambda p: (-(p["review_count"] or 0), -(p["rating"] or 0), p["name"]))

        filters = {
            "q": q,
            "categoria": category if category in CATEGORIES else "",
            "bairro": neighborhood if neighborhood in NEIGHBORHOODS else "",
            "ordenar": sort_by,
            "disponivel": only_avail,
            "nota": min_rating_str,
            "has_geo": lat is not None,
            "salvos": saved_mode,
        }
        return found, filters

    @app.middleware("http")
    async def security_and_readonly_middleware(request: Request, call_next):
        if READ_ONLY_DEMO and request.method == "POST":
            return HTMLResponse(
                layout_page(
                    "Modo demonstração",
                    '<section class="container section"><h1>Modo somente leitura ativo</h1>'
                    '<p>Esta instância está configurada apenas para visualização.</p>'
                    '<a class="button small" href="/">Voltar ao início</a></section>',
                ),
                status_code=403,
            )
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Permissions-Policy"] = "geolocation=(self), camera=(), microphone=()"
        if not request.url.path.startswith(("/docs", "/redoc", "/openapi.json")):
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
                "script-src 'self'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
            )
        return response

    # ----------------------------- API JSON -----------------------------

    @app.get("/api/health", tags=["Sistema"])
    def api_health():
        with open_db() as db:
            pros = int(db.scalar("SELECT COUNT(*) FROM professionals", default=0))
            return JSONResponse(
                {"status": "ok", "version": __version__, "database": db.engine_name, "professionals": pros}
            )

    @app.get("/api/profissionais", tags=["Profissionais"])
    def api_professionals(
        q: str = "",
        categoria: str = "",
        bairro: str = "",
        disponivel: str = "",
        nota: str = "",
        ordenar: str = "relevancia",
    ):
        with open_db() as db:
            found, _ = filter_pros(
                db,
                {
                    "q": q,
                    "categoria": categoria,
                    "bairro": bairro,
                    "disponivel": disponivel,
                    "nota": nota,
                    "ordenar": ordenar,
                },
            )
            return {"count": len(found), "items": found}

    # ----------------------------- PÁGINAS HTML -----------------------------

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def page_home(request: Request, msg: str = ""):
        with open_db() as db:
            user = current_user(db, request)
            featured = query_professionals(db, limit=6)
            stats = query_stats(db)
            return layout_page("Início", home_view(db, featured, stats), user, unread_count(db, user), msg[:180])

    @app.get("/buscar", response_class=HTMLResponse, include_in_schema=False)
    def page_search(request: Request, msg: str = ""):
        with open_db() as db:
            user = current_user(db, request)
            found, filters = filter_pros(db, dict(request.query_params))
            return layout_page(
                "Buscar profissionais", search_view(found, filters), user, unread_count(db, user), msg[:180]
            )

    @app.get("/perfil/{pro_id}", response_class=HTMLResponse, include_in_schema=False)
    def page_profile(pro_id: int, request: Request, msg: str = ""):
        with open_db() as db:
            user = current_user(db, request)
            pro = get_pro(db, pro_id)
            if not pro:
                return HTMLResponse(
                    layout_page(
                        "Não encontrado",
                        '<section class="container section"><h1>Profissional não encontrado</h1>'
                        '<a class="button small" href="/buscar">Voltar à busca</a></section>',
                        user,
                    ),
                    status_code=404,
                )
            return layout_page(pro["name"], profile_view(db, pro, user), user, unread_count(db, user), msg[:180])

    @app.get("/cadastro", response_class=HTMLResponse, include_in_schema=False)
    def page_signup(request: Request, role: str = "cliente"):
        with open_db() as db:
            user = current_user(db, request)
            return layout_page("Cadastro", auth_view(role=role), user, unread_count(db, user))

    @app.post("/cadastro", include_in_schema=False)
    def action_signup(
        request: Request,
        name: str = Form(""),
        email: str = Form(""),
        password: str = Form(""),
        role: str = Form("cliente"),
        category: str = Form(""),
        neighborhood: str = Form(""),
        whatsapp: str = Form(""),
    ):
        client_ip = request.client.host if request.client else "local"
        if not AUTH_LIMITER.allow(f"signup:{client_ip}"):
            return HTMLResponse(
                layout_page("Cadastro", auth_view(error="Muitas tentativas. Aguarde 1 minuto e tente novamente.")),
                status_code=429,
            )
        name_c = name.strip()[:80]
        email_c = email.strip().lower()[:255]
        wa_clean = clean_whatsapp(whatsapp)
        if (
            not name_c
            or "@" not in email_c
            or len(password) < 8
            or role not in ("cliente", "profissional")
            or (role == "profissional" and (category not in CATEGORIES or neighborhood not in NEIGHBORHOODS))
        ):
            return HTMLResponse(
                layout_page("Cadastro", auth_view(role=role, error="Revise os campos obrigatórios e tente novamente.")),
                status_code=400,
            )
        with open_db() as db:
            try:
                uid = db.insert_returning_id(
                    "INSERT INTO users (name, email, password_hash, role, created_at) VALUES (?, ?, ?, ?, ?)",
                    (name_c, email_c, password_hash(password), role, now_iso()),
                )
                if role == "profissional":
                    lat, lon = NEIGHBORHOODS[neighborhood]
                    db.execute(
                        "INSERT INTO professionals (user_id, category, neighborhood, whatsapp, lat, lon) VALUES (?, ?, ?, ?, ?, ?)",
                        (uid, category, neighborhood, wa_clean, lat, lon),
                    )
            except IntegrityConflictError:
                return HTMLResponse(
                    layout_page("Cadastro", auth_view(role=role, error="Este e-mail já está cadastrado.")),
                    status_code=409,
                )
            return login_redirect(db, uid, "/painel" if role == "profissional" else "/buscar")

    @app.get("/entrar", response_class=HTMLResponse, include_in_schema=False)
    def page_login(request: Request, next: str = ""):  # noqa: A002
        with open_db() as db:
            user = current_user(db, request)
            return layout_page("Entrar", auth_view(login=True, next_path=next), user, unread_count(db, user))

    @app.post("/entrar", include_in_schema=False)
    def action_login(
        request: Request,
        email: str = Form(""),
        password: str = Form(""),
        next: str = Form(""),  # noqa: A002
    ):
        client_ip = request.client.host if request.client else "local"
        if not AUTH_LIMITER.allow(f"login:{client_ip}"):
            return HTMLResponse(
                layout_page("Entrar", auth_view(login=True, error="Muitas tentativas de login. Aguarde 1 minuto.")),
                status_code=429,
            )
        with open_db() as db:
            row = db.fetchone("SELECT * FROM users WHERE email = ?", (email.strip().lower(),))
            if not row or not password_matches(password, row["password_hash"]):
                return HTMLResponse(
                    layout_page("Entrar", auth_view(login=True, next_path=next, error="E-mail ou senha incorretos.")),
                    status_code=401,
                )
            dest = safe_destination(next, "/painel" if row["role"] == "profissional" else "/buscar")
            return login_redirect(db, int(row["id"]), dest)

    @app.post("/sair", include_in_schema=False)
    def action_logout(request: Request, csrf: str = Form("")):
        with open_db() as db:
            user = current_user(db, request)
            if not check_csrf(user, csrf):
                return HTMLResponse(layout_page("Sessão expirada", '<section class="container section"><h1>Sessão expirada.</h1><a href="/entrar">Entrar</a></section>'), status_code=403)
            token = request.cookies.get("session", "")
            db.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash(token),))
            resp = RedirectResponse(url="/", status_code=303)
            resp.delete_cookie("session", path="/")
            return resp

    @app.get("/painel", response_class=HTMLResponse, include_in_schema=False)
    def page_dashboard(request: Request, msg: str = ""):
        with open_db() as db:
            user = current_user(db, request)
            if not user:
                return RedirectResponse(url="/entrar?" + urlencode({"next": "/painel"}), status_code=303)
            if user["role"] != "profissional":
                return RedirectResponse(url="/buscar", status_code=303)
            unread = unread_count(db, user)
            return layout_page("Meu painel", dashboard_view(db, user, unread), user, unread, msg[:180])

    @app.post("/perfil/editar", include_in_schema=False)
    def action_edit_profile(
        request: Request,
        csrf: str = Form(""),
        category: str = Form(""),
        neighborhood: str = Form(""),
        whatsapp: str = Form(""),
        response_time: str = Form(RESPONSE_TIMES[2]),
        bio: str = Form(""),
        experience: str = Form(""),
        price_text: str = Form(""),
        available: str = Form("0"),
    ):
        with open_db() as db:
            user = current_user(db, request)
            if not check_csrf(user, csrf) or user["role"] != "profissional":
                return HTMLResponse(layout_page("Acesso negado", '<section class="container section"><h1>Acesso negado.</h1></section>'), status_code=403)
            if category not in CATEGORIES or neighborhood not in NEIGHBORHOODS:
                return RedirectResponse(url="/painel?msg=" + quote("Categoria ou bairro inválido."), status_code=303)
            resp_t = response_time if response_time in RESPONSE_TIMES else RESPONSE_TIMES[2]
            raw_wa = whatsapp.strip()
            wa_clean = clean_whatsapp(raw_wa) if raw_wa else ""
            if raw_wa and not wa_clean:
                return RedirectResponse(
                    url="/painel?msg=" + quote("Informe um WhatsApp válido com DDD (10 ou 11 dígitos)."),
                    status_code=303,
                )
            lat, lon = NEIGHBORHOODS[neighborhood]
            db.execute(
                """UPDATE professionals
                   SET category=?, neighborhood=?, bio=?, experience=?, price_text=?,
                       whatsapp=?, response_time=?, available=?, lat=?, lon=?
                   WHERE user_id=?""",
                (
                    category,
                    neighborhood,
                    bio.strip()[:800],
                    experience.strip()[:600],
                    price_text.strip()[:100],
                    wa_clean,
                    resp_t,
                    1 if available == "1" else 0,
                    lat,
                    lon,
                    user["id"],
                ),
            )
            return RedirectResponse(url="/painel?msg=" + quote("Perfil atualizado com sucesso."), status_code=303)

    @app.post("/portfolio/adicionar", include_in_schema=False)
    async def action_add_portfolio(
        request: Request,
        csrf: str = Form(""),
        caption: str = Form(""),
        image: UploadFile = File(...),
    ):
        with open_db() as db:
            user = current_user(db, request)
            if not check_csrf(user, csrf) or user["role"] != "profissional":
                return HTMLResponse(layout_page("Acesso negado", '<section class="container section"><h1>Acesso negado.</h1></section>'), status_code=403)
            count = int(db.scalar("SELECT COUNT(*) FROM works WHERE professional_id = ?", (user["id"],), default=0))
            if count >= MAX_PORTFOLIO_ITEMS:
                return RedirectResponse(url="/painel?msg=" + quote(f"Limite de {MAX_PORTFOLIO_ITEMS} fotos atingido."), status_code=303)
            raw = await image.read()
            clean_bytes, ext = sanitize_image(raw)
            cap = caption.strip()[:100]
            if not clean_bytes or not ext or not cap:
                return RedirectResponse(
                    url="/painel?msg=" + quote("Envie JPG, PNG ou WEBP válido (até 3 MB) com legenda."),
                    status_code=303,
                )
            filename = secrets.token_hex(16) + ext
            UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
            (UPLOADS_DIR / filename).write_bytes(clean_bytes)
            db.execute(
                "INSERT INTO works (professional_id, image, caption, created_at) VALUES (?, ?, ?, ?)",
                (user["id"], "uploads/" + filename, cap, now_iso()),
            )
            return RedirectResponse(url="/painel?msg=" + quote("Foto adicionada ao portfólio."), status_code=303)

    @app.post("/portfolio/remover/{work_id}", include_in_schema=False)
    def action_remove_portfolio(work_id: int, request: Request, csrf: str = Form("")):
        with open_db() as db:
            user = current_user(db, request)
            if not check_csrf(user, csrf) or user["role"] != "profissional":
                return HTMLResponse(layout_page("Acesso negado", '<section class="container section"><h1>Acesso negado.</h1></section>'), status_code=403)
            row = db.fetchone(
                "SELECT id, image FROM works WHERE id = ? AND professional_id = ?",
                (work_id, user["id"]),
            )
            if row:
                db.execute("DELETE FROM works WHERE id = ?", (work_id,))
                if str(row["image"]).startswith("uploads/"):
                    fp = (STATIC_DIR / row["image"]).resolve()
                    if fp.is_relative_to(UPLOADS_DIR.resolve()) and fp.is_file():
                        fp.unlink(missing_ok=True)
            return RedirectResponse(url="/painel?msg=" + quote("Foto removida do portfólio."), status_code=303)

    @app.post("/iniciar/{pro_id}", include_in_schema=False)
    def action_start_chat(pro_id: int, request: Request, csrf: str = Form("")):
        with open_db() as db:
            user = current_user(db, request)
            if not check_csrf(user, csrf) or user["role"] != "cliente":
                return HTMLResponse(layout_page("Acesso negado", '<section class="container section"><h1>Acesso negado.</h1></section>'), status_code=403)
            if not get_pro(db, pro_id):
                return HTMLResponse(layout_page("Não encontrado", '<section class="container section"><h1>Profissional não encontrado.</h1></section>'), status_code=404)
            existing = db.fetchone(
                "SELECT id FROM conversations WHERE client_id = ? AND professional_id = ?",
                (user["id"], pro_id),
            )
            if existing:
                cid = int(existing["id"])
            else:
                cid = db.insert_returning_id(
                    "INSERT INTO conversations (client_id, professional_id, created_at) VALUES (?, ?, ?)",
                    (user["id"], pro_id, now_iso()),
                )
            return RedirectResponse(url=f"/conversa/{cid}", status_code=303)

    @app.get("/conversas", response_class=HTMLResponse, include_in_schema=False)
    def page_conversations(request: Request, msg: str = ""):
        with open_db() as db:
            user = current_user(db, request)
            if not user:
                return RedirectResponse(url="/entrar?" + urlencode({"next": "/conversas"}), status_code=303)
            return layout_page("Conversas", conversations_view(db, user), user, unread_count(db, user), msg[:180])

    @app.get("/conversa/{conv_id}", response_class=HTMLResponse, include_in_schema=False)
    def page_chat(conv_id: int, request: Request):
        with open_db() as db:
            user = current_user(db, request)
            if not user:
                return RedirectResponse(url="/entrar?" + urlencode({"next": f"/conversa/{conv_id}"}), status_code=303)
            conv = db.fetchone(
                "SELECT * FROM conversations WHERE id = ? AND (client_id = ? OR professional_id = ?)",
                (conv_id, user["id"], user["id"]),
            )
            if not conv:
                return HTMLResponse(layout_page("Não encontrado", '<section class="container section"><h1>Conversa não encontrada.</h1></section>', user), status_code=404)
            db.execute(
                "UPDATE messages SET read_at = ? WHERE conversation_id = ? AND sender_id <> ? AND read_at IS NULL",
                (now_iso(), conv["id"], user["id"]),
            )
            return layout_page("Conversa", chat_view(db, user, conv), user, unread_count(db, user))

    @app.post("/conversa/{conv_id}", include_in_schema=False)
    def action_send_message(conv_id: int, request: Request, csrf: str = Form(""), body: str = Form("")):
        with open_db() as db:
            user = current_user(db, request)
            if not check_csrf(user, csrf):
                return HTMLResponse(layout_page("Acesso negado", '<section class="container section"><h1>Sessão expirada.</h1></section>'), status_code=403)
            conv = db.fetchone(
                "SELECT * FROM conversations WHERE id = ? AND (client_id = ? OR professional_id = ?)",
                (conv_id, user["id"], user["id"]),
            )
            if not conv:
                return HTMLResponse(layout_page("Não encontrado", '<section class="container section"><h1>Conversa não encontrada.</h1></section>', user), status_code=404)
            clean_body = body.strip()[:1500]
            if clean_body:
                db.execute(
                    "INSERT INTO messages (conversation_id, sender_id, body, created_at) VALUES (?, ?, ?, ?)",
                    (conv["id"], user["id"], clean_body, now_iso()),
                )
            return RedirectResponse(url=f"/conversa/{conv_id}", status_code=303)

    @app.post("/avaliar/{pro_id}", include_in_schema=False)
    def action_review(
        pro_id: int,
        request: Request,
        csrf: str = Form(""),
        rating: int = Form(0),
        comment: str = Form(""),
    ):
        with open_db() as db:
            user = current_user(db, request)
            if not check_csrf(user, csrf) or user["role"] != "cliente":
                return HTMLResponse(layout_page("Acesso negado", '<section class="container section"><h1>Acesso negado.</h1></section>'), status_code=403)
            if not get_pro(db, pro_id):
                return HTMLResponse(layout_page("Não encontrado", '<section class="container section"><h1>Profissional não encontrado.</h1></section>'), status_code=404)
            clean_comment = comment.strip()[:500]
            if rating not in range(1, 6) or not clean_comment:
                return RedirectResponse(
                    url=f"/perfil/{pro_id}?msg=" + quote("Escolha uma nota de 1 a 5 e escreva um comentário."),
                    status_code=303,
                )
            db.execute(
                """INSERT INTO reviews (client_id, professional_id, rating, comment, created_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(client_id, professional_id)
                   DO UPDATE SET rating = excluded.rating, comment = excluded.comment, created_at = excluded.created_at""",
                (user["id"], pro_id, rating, clean_comment, now_iso()),
            )
            return RedirectResponse(url=f"/perfil/{pro_id}?msg=" + quote("Avaliação publicada com sucesso!"), status_code=303)

    return app


app = create_app()
