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
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from ondetem import __version__
import os
import json
from ondetem.config import (
    ADMIN_EMAILS,
    APP_BASE_URL,
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
    sanitize_avatar,
    sanitize_image,
    token_hash,
    turnstile_site_key,
    verify_math_challenge,
    verify_turnstile,
    whatsapp_link,
)
from ondetem.mailer import mailer_backend_name, send_password_reset_email, send_verification_email
from ondetem.storage import delete_stored_image, resolve_image_url, storage_backend_name, upload_image
from ondetem.views import (
    account_view,
    admin_view,
    auth_view,
    forgot_password_view,
    privacy_view,
    reset_password_view,
    terms_view,
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

    def is_admin_email(email: str, db: DBSession) -> bool:
        env_admins = {e.strip().lower() for e in os.environ.get("ADMIN_EMAILS", "").split(",") if e.strip()}
        admins = env_admins or ADMIN_EMAILS
        if admins:
            return email.strip().lower() in admins
        # Em ambiente local SQLite sem ADMIN_EMAILS configurado, libera a conta demo para teste
        return (not db.is_postgres) and email.strip().lower() == "cliente@ondetem.local"

    def current_user(db: DBSession, request: Request) -> dict[str, Any] | None:
        token = request.cookies.get("session", "")
        if not token:
            return None
        row = db.fetchone(
            """SELECT u.id, u.name, u.email, u.role, COALESCE(u.email_verified, 1) AS email_verified, s.csrf
               FROM sessions s JOIN users u ON u.id = s.user_id
               WHERE s.token_hash = ? AND s.expires_at > ?""",
            (token_hash(token), now_iso()),
        )
        if row:
            row["is_admin"] = is_admin_email(str(row["email"]), db)
        return row

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
            ts_script = " https://challenges.cloudflare.com" if turnstile_site_key() else ""
            ts_frame = " frame-src https://challenges.cloudflare.com;" if turnstile_site_key() else ""
            response.headers["Content-Security-Policy"] = (
                f"default-src 'self'; img-src 'self' data: https://res.cloudinary.com; style-src 'self' 'unsafe-inline'; "
                f"script-src 'self'{ts_script};{ts_frame} base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
            )
        return response


    # ----------------------------- PWA (MANIFEST + SERVICE WORKER) -----------------------------

    @app.get("/manifest.webmanifest", include_in_schema=False)
    def pwa_manifest():
        return FileResponse(
            STATIC_DIR / "manifest.json",
            media_type="application/manifest+json",
            headers={"Cache-Control": "public, max-age=3600"},
        )

    @app.get("/sw.js", include_in_schema=False)
    def pwa_service_worker():
        return FileResponse(
            STATIC_DIR / "sw.js",
            media_type="application/javascript",
            headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"},
        )


    # ----------------------------- SEO (ROBOTS + SITEMAP) -----------------------------

    @app.get("/robots.txt", response_class=PlainTextResponse, include_in_schema=False)
    def seo_robots():
        base = os.environ.get("APP_BASE_URL", APP_BASE_URL).rstrip("/")
        return (
            "User-agent: *\n"
            "Allow: /\n"
            "Disallow: /admin\n"
            "Disallow: /painel\n"
            "Disallow: /conta\n"
            "Disallow: /conversas\n"
            "Disallow: /conversa/\n"
            f"Sitemap: {base}/sitemap.xml\n"
        )

    @app.get("/sitemap.xml", include_in_schema=False)
    def seo_sitemap():
        base = os.environ.get("APP_BASE_URL", APP_BASE_URL).rstrip("/")
        urls = [f"{base}/", f"{base}/buscar", f"{base}/termos", f"{base}/privacidade"]
        for cat in CATEGORIES:
            urls.append(f"{base}/buscar?categoria={quote(cat)}")
        with open_db() as db:
            for row in db.fetchall("SELECT user_id FROM professionals ORDER BY user_id ASC"):
                urls.append(f"{base}/perfil/{row['user_id']}")
        items = "".join(f"<url><loc>{u}</loc></url>" for u in urls)
        xml = f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{items}</urlset>'
        return Response(content=xml, media_type="application/xml")

    # ----------------------------- API JSON -----------------------------

    @app.api_route("/api/health", methods=["GET", "HEAD"], tags=["Sistema"])
    def api_health():
        with open_db() as db:
            pros = int(db.scalar("SELECT COUNT(*) FROM professionals", default=0))
            return JSONResponse(
                {"status": "ok", "version": __version__, "database": db.engine_name, "storage": storage_backend_name(), "mailer": mailer_backend_name(), "antibot": "turnstile" if turnstile_site_key() else "signed_challenge", "professionals": pros}
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
            return layout_page("Início", home_view(db, featured, stats), user, unread_count(db, user), msg[:180], canonical_path="/")

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
            base = os.environ.get("APP_BASE_URL", APP_BASE_URL).rstrip("/")
            rating_str = f" · ★ {float(pro['rating']):.1f}" if pro.get("review_count") else ""
            og_t = f"{pro['name']} — {pro['category']} em {pro['neighborhood']}, Manaus{rating_str}"
            og_d = (pro.get("bio") or f"Contrate {pro['name']} ({pro['category']}) em {pro['neighborhood']}, Manaus pelo OndeTem.")[:160]
            raw_av = str(pro.get("avatar_url") or "")
            if raw_av.startswith("https://"):
                og_img = raw_av
            elif raw_av:
                og_img = base + resolve_image_url(raw_av)
            else:
                og_img = base + "/static/og-ondetem.png"
            ld = {
                "@context": "https://schema.org",
                "@type": "LocalBusiness",
                "name": f"{pro['name']} ({pro['category']})",
                "description": og_d,
                "image": og_img,
                "url": f"{base}/perfil/{pro['user_id']}",
                "address": {
                    "@type": "PostalAddress",
                    "addressLocality": "Manaus",
                    "addressRegion": "AM",
                    "addressCountry": "BR",
                    "streetAddress": pro["neighborhood"],
                },
            }
            if pro.get("review_count"):
                ld["aggregateRating"] = {
                    "@type": "AggregateRating",
                    "ratingValue": round(float(pro["rating"]), 1),
                    "reviewCount": int(pro["review_count"]),
                }
            ld_script = f'<script type="application/ld+json">{json.dumps(ld, ensure_ascii=False)}</script>'
            return layout_page(
                pro["name"],
                profile_view(db, pro, user),
                user,
                unread_count(db, user),
                msg[:180],
                og_title=og_t,
                og_desc=og_d,
                og_image=og_img,
                canonical_path=f"/perfil/{pro['user_id']}",
                extra_head=ld_script,
            )

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
        accept_terms: str = Form(""),
        website_url: str = Form(""),
        captcha_token: str = Form(""),
        captcha_answer: str = Form(""),
        cf_turnstile_response: str = Form("", alias="cf-turnstile-response"),
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
        if website_url.strip():
            return HTMLResponse(
                layout_page("Cadastro", auth_view(role=role, error="Verificação anti-robô falhou. Tente novamente.")),
                status_code=400,
            )
        if turnstile_site_key():
            if not verify_turnstile(cf_turnstile_response, client_ip):
                return HTMLResponse(
                    layout_page("Cadastro", auth_view(role=role, error="Confirme a verificação anti-robô antes de continuar.")),
                    status_code=400,
                )
        else:
            if not verify_math_challenge(captcha_token, captcha_answer):
                return HTMLResponse(
                    layout_page("Cadastro", auth_view(role=role, error="Resposta da verificação anti-robô incorreta. Tente novamente.")),
                    status_code=400,
                )
        if accept_terms != "1":
            return HTMLResponse(
                layout_page("Cadastro", auth_view(role=role, error="Você precisa aceitar os Termos de Uso e a Política de Privacidade (LGPD).")),
                status_code=400,
            )
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
                    "INSERT INTO users (name, email, password_hash, role, email_verified, created_at) VALUES (?, ?, ?, ?, 0, ?)",
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
            vtok = secrets.token_urlsafe(32)
            vexp = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat(timespec="seconds")
            db.execute(
                "INSERT INTO email_verifications (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
                (token_hash(vtok), uid, vexp),
            )
            base_url = str(request.base_url).rstrip("/")
            send_verification_email(email_c, name_c, f"{base_url}/verificar-email?token={quote(vtok)}")
            dest = "/painel?msg=" + quote("Conta criada! Confirme o link enviado ao seu e-mail.") if role == "profissional" else "/buscar?msg=" + quote("Conta criada! Confirme o link enviado ao seu e-mail.")
            return login_redirect(db, uid, dest)

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


    @app.post("/perfil/foto", include_in_schema=False)
    async def action_update_avatar(
        request: Request,
        csrf: str = Form(""),
        avatar: UploadFile = File(...),
    ):
        with open_db() as db:
            user = current_user(db, request)
            if not check_csrf(user, csrf) or user["role"] != "profissional":
                return HTMLResponse(layout_page("Acesso negado", '<section class="container section"><h1>Acesso negado.</h1></section>'), status_code=403)
            raw = await avatar.read()
            clean_bytes, ext = sanitize_avatar(raw)
            if not clean_bytes or not ext:
                return RedirectResponse(
                    url="/painel?msg=" + quote("Envie uma foto JPG, PNG ou WEBP válida de até 3 MB."),
                    status_code=303,
                )
            old_row = db.fetchone("SELECT avatar_url FROM professionals WHERE user_id = ?", (user["id"],))
            stored_avatar = upload_image(clean_bytes, ext, folder="ondetem/avatars")
            db.execute("UPDATE professionals SET avatar_url = ? WHERE user_id = ?", (stored_avatar, user["id"]))
            if old_row and old_row.get("avatar_url"):
                delete_stored_image(str(old_row["avatar_url"]))
            return RedirectResponse(url="/painel?msg=" + quote("Foto de perfil atualizada!"), status_code=303)

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
            stored_img = upload_image(clean_bytes, ext, folder="ondetem/portfolio")
            db.execute(
                "INSERT INTO works (professional_id, image, caption, created_at) VALUES (?, ?, ?, ?)",
                (user["id"], stored_img, cap, now_iso()),
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
                delete_stored_image(str(row["image"]))
            return RedirectResponse(url="/painel?msg=" + quote("Foto removida do portfólio."), status_code=303)

    @app.post("/iniciar/{pro_id}", include_in_schema=False)
    def action_start_chat(pro_id: int, request: Request, csrf: str = Form("")):
        with open_db() as db:
            user = current_user(db, request)
            if not check_csrf(user, csrf) or user["role"] != "cliente":
                return HTMLResponse(layout_page("Acesso negado", '<section class="container section"><h1>Acesso negado.</h1></section>'), status_code=403)
            if not user.get("email_verified", 1):
                return RedirectResponse(
                    url=f"/perfil/{pro_id}?msg=" + quote("Confirme seu e-mail antes de publicar uma avaliação."),
                    status_code=303,
                )
            if False:
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


    # ------------------- RECUPERAÇÃO DE SENHA & LGPD -------------------

    @app.get("/esqueci-senha", response_class=HTMLResponse, include_in_schema=False)
    def page_forgot_password(request: Request, enviado: str = ""):
        with open_db() as db:
            user = current_user(db, request)
            return layout_page("Esqueci minha senha", forgot_password_view(sent=(enviado == "1")), user, unread_count(db, user))

    @app.post("/esqueci-senha", include_in_schema=False)
    def action_forgot_password(request: Request, email: str = Form("")):
        client_ip = request.client.host if request.client else "local"
        if not AUTH_LIMITER.allow(f"forgot:{client_ip}"):
            return HTMLResponse(
                layout_page("Esqueci minha senha", forgot_password_view(error="Muitas solicitações. Aguarde 1 minuto e tente novamente.")),
                status_code=429,
            )
        clean_email = email.strip().lower()[:255]
        if "@" not in clean_email:
            return HTMLResponse(
                layout_page("Esqueci minha senha", forgot_password_view(error="Informe um e-mail válido.")),
                status_code=400,
            )
        with open_db() as db:
            row = db.fetchone("SELECT id, name, email FROM users WHERE email = ?", (clean_email,))
            if row:
                raw_token = secrets.token_urlsafe(32)
                expiry = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat(timespec="seconds")
                db.execute("DELETE FROM password_resets WHERE user_id = ? OR expires_at <= ?", (row["id"], now_iso()))
                db.execute(
                    "INSERT INTO password_resets (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
                    (token_hash(raw_token), row["id"], expiry),
                )
                base_url = str(request.base_url).rstrip("/")
                reset_url = f"{base_url}/redefinir-senha?token={quote(raw_token)}"
                send_password_reset_email(str(row["email"]), str(row["name"]), reset_url)
        return RedirectResponse(url="/esqueci-senha?enviado=1", status_code=303)

    @app.get("/redefinir-senha", response_class=HTMLResponse, include_in_schema=False)
    def page_reset_password(request: Request, token: str = ""):
        with open_db() as db:
            user = current_user(db, request)
            rec = (
                db.fetchone(
                    "SELECT * FROM password_resets WHERE token_hash = ? AND used_at IS NULL AND expires_at > ?",
                    (token_hash(token), now_iso()),
                )
                if token
                else None
            )
            return layout_page(
                "Redefinir senha",
                reset_password_view(token=token, invalid=(rec is None)),
                user,
                unread_count(db, user),
            )

    @app.post("/redefinir-senha", include_in_schema=False)
    def action_reset_password(
        request: Request,
        token: str = Form(""),
        password: str = Form(""),
        confirm_password: str = Form(""),
    ):
        if len(password) < 8:
            return HTMLResponse(
                layout_page("Redefinir senha", reset_password_view(token=token, error="A nova senha deve ter no mínimo 8 caracteres.")),
                status_code=400,
            )
        if password != confirm_password:
            return HTMLResponse(
                layout_page("Redefinir senha", reset_password_view(token=token, error="As senhas digitadas não conferem.")),
                status_code=400,
            )
        with open_db() as db:
            rec = db.fetchone(
                "SELECT * FROM password_resets WHERE token_hash = ? AND used_at IS NULL AND expires_at > ?",
                (token_hash(token), now_iso()),
            )
            if not rec:
                return HTMLResponse(
                    layout_page("Redefinir senha", reset_password_view(invalid=True)),
                    status_code=400,
                )
            db.execute("UPDATE users SET password_hash = ? WHERE id = ?", (password_hash(password), rec["user_id"]))
            db.execute("UPDATE password_resets SET used_at = ? WHERE token_hash = ?", (now_iso(), rec["token_hash"]))
            db.execute("DELETE FROM sessions WHERE user_id = ?", (rec["user_id"],))
        return RedirectResponse(url="/entrar?msg=" + quote("Senha redefinida com sucesso! Entre com sua nova senha."), status_code=303)

    @app.get("/termos", response_class=HTMLResponse, include_in_schema=False)
    def page_terms(request: Request):
        with open_db() as db:
            user = current_user(db, request)
            return layout_page("Termos de Uso", terms_view(), user, unread_count(db, user))

    @app.get("/privacidade", response_class=HTMLResponse, include_in_schema=False)
    def page_privacy(request: Request):
        with open_db() as db:
            user = current_user(db, request)
            return layout_page("Política de Privacidade (LGPD)", privacy_view(), user, unread_count(db, user))

    @app.get("/conta", response_class=HTMLResponse, include_in_schema=False)
    def page_account(request: Request, msg: str = ""):
        with open_db() as db:
            user = current_user(db, request)
            if not user:
                return RedirectResponse(url="/entrar?" + urlencode({"next": "/conta"}), status_code=303)
            return layout_page("Minha conta", account_view(user), user, unread_count(db, user), msg[:180])

    @app.post("/conta/excluir", include_in_schema=False)
    def action_delete_account(request: Request, csrf: str = Form(""), password: str = Form("")):
        with open_db() as db:
            user = current_user(db, request)
            if not check_csrf(user, csrf):
                return HTMLResponse(layout_page("Acesso negado", '<section class="container section"><h1>Sessão expirada.</h1></section>'), status_code=403)
            row = db.fetchone("SELECT password_hash FROM users WHERE id = ?", (user["id"],))
            if not row or not password_matches(password, row["password_hash"]):
                return HTMLResponse(
                    layout_page("Minha conta", account_view(user, error="Senha incorreta. Nenhum dado foi apagado."), user, unread_count(db, user)),
                    status_code=401,
                )
            works = db.fetchall("SELECT image FROM works WHERE professional_id = ?", (user["id"],))
            pro = db.fetchone("SELECT avatar_url FROM professionals WHERE user_id = ?", (user["id"],))
            for w in works:
                delete_stored_image(str(w["image"]))
            if pro and pro.get("avatar_url"):
                delete_stored_image(str(pro["avatar_url"]))
            db.execute("DELETE FROM users WHERE id = ?", (user["id"],))
            resp = RedirectResponse(url="/?msg=" + quote("Sua conta e seus dados foram excluídos permanentemente."), status_code=303)
            resp.delete_cookie("session", path="/")
            return resp


    # ------------------- CLIQUES WHATSAPP & PAINEL ADMIN -------------------

    @app.get("/contato/whatsapp/{pro_id}", include_in_schema=False)
    def action_whatsapp_redirect(pro_id: int):
        with open_db() as db:
            pro = get_pro(db, pro_id)
            if not pro or not pro.get("whatsapp"):
                return RedirectResponse(url="/buscar", status_code=303)
            db.execute(
                "UPDATE professionals SET whatsapp_clicks = COALESCE(whatsapp_clicks, 0) + 1 WHERE user_id = ?",
                (pro_id,),
            )
            db.execute(
                "INSERT INTO click_events (professional_id, channel, created_at) VALUES (?, 'whatsapp', ?)",
                (pro_id, now_iso()),
            )
            target = whatsapp_link(str(pro["whatsapp"]), str(pro["name"]), str(pro["category"]))
            return RedirectResponse(url=target, status_code=302)

    @app.get("/admin", response_class=HTMLResponse, include_in_schema=False)
    def page_admin(request: Request, msg: str = ""):
        with open_db() as db:
            user = current_user(db, request)
            if not user:
                return RedirectResponse(url="/entrar?" + urlencode({"next": "/admin"}), status_code=303)
            if not user.get("is_admin"):
                return HTMLResponse(
                    layout_page(
                        "Acesso restrito",
                        '<section class="container section"><h1>Área restrita ao administrador</h1>'
                        '<p>Adicione seu e-mail na variável <code>ADMIN_EMAILS</code> no Render para liberar acesso.</p>'
                        '<a class="button small" href="/">Voltar ao início</a></section>',
                        user,
                        unread_count(db, user),
                    ),
                    status_code=403,
                )
            cutoff_7d = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat(timespec="seconds")
            summary = {
                "users": int(db.scalar("SELECT COUNT(*) FROM users", default=0)),
                "pros": int(db.scalar("SELECT COUNT(*) FROM professionals", default=0)),
                "verified": int(db.scalar("SELECT COUNT(*) FROM professionals WHERE verified = 1", default=0)),
                "reviews": int(db.scalar("SELECT COUNT(*) FROM reviews", default=0)),
                "avg_rating": float(db.scalar("SELECT COALESCE(AVG(rating), 0) FROM reviews", default=0) or 0),
                "conversations": int(db.scalar("SELECT COUNT(*) FROM conversations", default=0)),
                "wa_clicks": int(db.scalar("SELECT COALESCE(SUM(whatsapp_clicks), 0) FROM professionals", default=0) or 0),
                "wa_clicks_7d": int(db.scalar("SELECT COUNT(*) FROM click_events WHERE created_at >= ?", (cutoff_7d,), default=0)),
            }
            pros = db.fetchall(
                """SELECT p.*, u.name, u.email,
                    (SELECT AVG(rating) FROM reviews r WHERE r.professional_id = p.user_id) AS rating,
                    (SELECT COUNT(*) FROM reviews r WHERE r.professional_id = p.user_id) AS review_count
                   FROM professionals p JOIN users u ON u.id = p.user_id
                   ORDER BY COALESCE(p.whatsapp_clicks, 0) DESC, p.verified DESC, u.name ASC"""
            )
            recent_reviews = db.fetchall(
                """SELECT r.id, r.rating, r.comment, r.created_at,
                          c.name AS client_name, pr.name AS pro_name
                   FROM reviews r
                   JOIN users c ON c.id = r.client_id
                   JOIN users pr ON pr.id = r.professional_id
                   ORDER BY r.id DESC LIMIT 20"""
            )
            top_neighborhoods = db.fetchall(
                """SELECT neighborhood, COUNT(*) AS total
                   FROM professionals GROUP BY neighborhood
                   ORDER BY total DESC, neighborhood ASC LIMIT 6"""
            )
            return layout_page(
                "Painel Admin",
                admin_view(user, summary, pros, recent_reviews, top_neighborhoods),
                user,
                unread_count(db, user),
                msg[:180],
            )

    @app.post("/admin/verificar/{pro_id}", include_in_schema=False)
    def action_admin_verify(pro_id: int, request: Request, csrf: str = Form("")):
        with open_db() as db:
            user = current_user(db, request)
            if not check_csrf(user, csrf) or not user.get("is_admin"):
                return HTMLResponse(layout_page("Acesso negado", '<section class="container section"><h1>Acesso negado.</h1></section>'), status_code=403)
            row = db.fetchone("SELECT verified FROM professionals WHERE user_id = ?", (pro_id,))
            if not row:
                return RedirectResponse(url="/admin?msg=" + quote("Profissional não encontrado."), status_code=303)
            new_val = 0 if row["verified"] else 1
            db.execute("UPDATE professionals SET verified = ? WHERE user_id = ?", (new_val, pro_id))
            msg = "Selo Verificado aprovado!" if new_val else "Selo Verificado removido."
            return RedirectResponse(url="/admin?msg=" + quote(msg), status_code=303)

    @app.post("/admin/avaliacao/remover/{review_id}", include_in_schema=False)
    def action_admin_delete_review(review_id: int, request: Request, csrf: str = Form("")):
        with open_db() as db:
            user = current_user(db, request)
            if not check_csrf(user, csrf) or not user.get("is_admin"):
                return HTMLResponse(layout_page("Acesso negado", '<section class="container section"><h1>Acesso negado.</h1></section>'), status_code=403)
            db.execute("DELETE FROM reviews WHERE id = ?", (review_id,))
            return RedirectResponse(url="/admin?msg=" + quote("Avaliação removida pela moderação."), status_code=303)


    @app.get("/verificar-email", include_in_schema=False)
    def action_verify_email(token: str = ""):
        if not token:
            return RedirectResponse(url="/?msg=" + quote("Link de verificação inválido."), status_code=303)
        with open_db() as db:
            rec = db.fetchone(
                "SELECT * FROM email_verifications WHERE token_hash = ? AND used_at IS NULL AND expires_at > ?",
                (token_hash(token), now_iso()),
            )
            if not rec:
                return RedirectResponse(url="/?msg=" + quote("Link de verificação expirado ou já utilizado."), status_code=303)
            db.execute("UPDATE users SET email_verified = 1 WHERE id = ?", (rec["user_id"],))
            db.execute("UPDATE email_verifications SET used_at = ? WHERE token_hash = ?", (now_iso(), rec["token_hash"]))
        return RedirectResponse(url="/?msg=" + quote("E-mail confirmado com sucesso! Sua conta está 100% ativa."), status_code=303)

    @app.post("/reenviar-verificacao", include_in_schema=False)
    def action_resend_verification(request: Request, csrf: str = Form("")):
        with open_db() as db:
            user = current_user(db, request)
            if not check_csrf(user, csrf):
                return HTMLResponse(layout_page("Acesso negado", '<section class="container section"><h1>Sessão expirada.</h1></section>'), status_code=403)
            if user.get("email_verified"):
                return RedirectResponse(url="/?msg=" + quote("Seu e-mail já está confirmado."), status_code=303)
            vtok = secrets.token_urlsafe(32)
            vexp = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat(timespec="seconds")
            db.execute("DELETE FROM email_verifications WHERE user_id = ?", (user["id"],))
            db.execute(
                "INSERT INTO email_verifications (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
                (token_hash(vtok), user["id"], vexp),
            )
            base_url = str(request.base_url).rstrip("/")
            send_verification_email(str(user["email"]), str(user["name"]), f"{base_url}/verificar-email?token={quote(vtok)}")
        return RedirectResponse(url="/?msg=" + quote("Novo link de confirmação enviado ao seu e-mail!"), status_code=303)

    return app


app = create_app()
