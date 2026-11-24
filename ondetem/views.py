"""Camada de visualização HTML do OndeTem (acessível, semântica e mobile-first)."""

from __future__ import annotations

import sqlite3
from urllib.parse import urlencode

from ondetem.config import APP_BASE_URL, CATEGORIES, CATEGORY_GROUPS, NEIGHBORHOODS, READ_ONLY_DEMO, RESPONSE_TIMES
from ondetem.storage import resolve_image_url
from ondetem.security import (
    esc,
    generate_math_challenge,
    turnstile_site_key,
    format_manaus_date,
    format_manaus_time,
    format_phone_display,
    whatsapp_link,
)

# Ícones SVG limpos (estilo Lucide, 24x24) para identidade visual profissional
ICONS: dict[str, str] = {
    "bolt": '<path d="M13 2 4 14h7l-1 8 9-12h-7l1-8z"/>',
    "droplet": '<path d="M12 2.7 6.3 9.4a7 7 0 1 0 11.4 0L12 2.7z"/>',
    "snowflake": '<path d="M12 2v20M2 12h20M4.9 4.9l14.2 14.2M19.1 4.9 4.9 19.1"/>',
    "brush": '<path d="m18.4 2.6 3 3-9.8 9.8-3.5.5.5-3.5 9.8-9.8z"/><path d="M7 17c-1.7 0-3 1.3-3 3 0 .8-.5 1.5-1.2 1.8.8.4 1.8.2 2.7.2 2.5 0 4.5-2 4.5-4.5"/>',
    "wrench": '<path d="M14.7 6.3a4 4 0 0 0 5.6 5.6l-1.6 1.6a5.5 5.5 0 0 1-7.2.6l-5.7 5.7a2 2 0 0 1-2.8-2.8l5.7-5.7a5.5 5.5 0 0 1 .6-7.2l1.6-1.6a4 4 0 0 0 3.8 3.8z"/>',
    "key": '<circle cx="7.5" cy="15.5" r="4.5"/><path d="m21 2-9.6 9.6M15.5 7.5 19 11M18 5l2.5 2.5"/>',
    "hammer": '<path d="m15 12-8.5 8.5a2.1 2.1 0 0 1-3-3L12 9"/><path d="M17.6 15 22 10.6l-5.6-5.6-4.4 4.4"/><path d="m12 6 3-3 6 6-3 3"/>',
    "sparkles": '<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3z"/><path d="M19 16l.9 2.1L22 19l-2.1.9L19 22l-.9-2.1L16 19l2.1-.9L19 16z"/>',
    "pin": '<path d="M12 21s-6-5.4-6-10a6 6 0 1 1 12 0c0 4.6-6 10-6 10z"/><circle cx="12" cy="11" r="2.2"/>',
    "star": '<path d="m12 2.6 2.9 5.9 6.5.9-4.7 4.6 1.1 6.5L12 17.4l-5.8 3.1 1.1-6.5-4.7-4.6 6.5-.9L12 2.6z" fill="currentColor"/>',
    "check": '<path d="M20 6 9 17l-5-5"/>',
    "shield": '<path d="M12 2 4 5v6c0 5.3 3.4 9.9 8 11 4.6-1.1 8-5.7 8-11V5l-8-3z"/><path d="m9 12 2 2 4-4"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/>',
    "whatsapp": '<path d="M20 11.5A8.5 8.5 0 0 1 7.6 19l-4.1 1.1 1.1-4A8.5 8.5 0 1 1 20 11.5z"/><path d="M9.5 8.8c.2-.4.4-.4.7-.4h.5c.2 0 .4.1.5.4l.7 1.6c.1.3.1.5-.1.7l-.5.6c.5.9 1.3 1.7 2.2 2.2l.6-.5c.2-.2.4-.2.7-.1l1.6.7c.3.1.4.3.4.5v.5c0 .3 0 .5-.4.7-.5.3-1.4.5-2.6.1-1.6-.6-3.7-2.6-4.3-4.3-.4-1.2-.2-2.1.1-2.7z"/>',
    "chat": '<path d="M21 15a2 2 0 0 1-2 2H8l-5 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
    "heart": '<path d="M12 20.5 4.6 13.4a4.7 4.7 0 0 1 6.7-6.6L12 7.5l.7-.7a4.7 4.7 0 0 1 6.7 6.6L12 20.5z"/>',
    "share": '<circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><path d="m8.6 13.5 6.8 4M15.4 6.5l-6.8 4"/>',
    "trash": '<path d="M3 6h18M8 6V4h8v2M6 6l1 14h10l1-14M10 11v6M14 11v6"/>',
    "target": '<circle cx="12" cy="12" r="7"/><circle cx="12" cy="12" r="2"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3"/>',
    "menu": '<path d="M4 6h16M4 12h16M4 18h16"/>',
    "car": '<path d="M5 17h14M6 17l-1-5 2.5-5h9L19 12l-1 5"/><circle cx="7.5" cy="17.5" r="1.5"/><circle cx="16.5" cy="17.5" r="1.5"/>',
    "laptop": '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M2 20h20"/>',
    "calculator": '<rect x="4" y="2" width="16" height="20" rx="2"/><path d="M8 6h8M8 11h2M14 11h2M8 15h2M14 15h2M8 19h8"/>',
    "music": '<path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/>',
    "truck": '<path d="M1 3h15v13H1zM16 8h4l3 3v5h-7V8z"/><circle cx="5.5" cy="18.5" r="2.5"/><circle cx="18.5" cy="18.5" r="2.5"/>',
    "leaf": '<path d="M11 20A7 7 0 0 1 9.8 6.1C15.5 5 17 4.5 19 2c1 2 2 4.2 2 8 0 5.5-4.8 10-10 10z"/><path d="M2 21c0-3 1.9-5.4 5.1-6.5"/>',
    "camera": '<path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/>',
    "palette": '<circle cx="13.5" cy="6.5" r=".8"/><circle cx="17.5" cy="10.5" r=".8"/><circle cx="8.5" cy="7.5" r=".8"/><circle cx="6.5" cy="12.5" r=".8"/><path d="M12 2a10 10 0 0 0 0 20c1.4 0 2.5-1.1 2.5-2.5 0-.6-.2-1.2-.6-1.6-.4-.4-.6-1-.6-1.6 0-1.4 1.1-2.5 2.5-2.5H18a4 4 0 0 0 4-4c0-5-4.5-7.8-10-7.8z"/>',
    "book": '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/>',
    "dumbbell": '<path d="M6.5 6.5v11M17.5 6.5v11M3 9v6M21 9v6M6.5 12h11"/>',
    "scissors": '<circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M20 4 8.1 15.9M14.5 14.5 20 20M8.1 8.1 12 12"/>',
    "users": '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.9M16 3.1a4 4 0 0 1 0 7.8"/>',
    "cake": '<path d="M20 21v-8a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8"/><path d="M4 16s.5-1 2-1 2.5 2 4 2 2.5-2 4-2 2.5 2 4 2 2-1 2-1"/><path d="M2 21h20M7 8v3M12 8v3M17 8v3M7 4h.01M12 4h.01M17 4h.01"/>',
    "utensils": '<path d="M3 2v7c0 1.1.9 2 2 2h4a2 2 0 0 0 2-2V2M7 2v20M21 15V2v0a5 5 0 0 0-5 5v6c0 1.1.9 2 2 2h3zm0 0v7"/>',
    "chef": '<path d="M6 13.87A4 4 0 0 1 7.41 6a5.11 5.11 0 0 1 1.05-1.54 5 5 0 0 1 7.08 0A5.11 5.11 0 0 1 16.59 6 4 4 0 0 1 18 13.87V21H6z"/><line x1="6" y1="17" x2="18" y2="17"/>',
    "party": '<path d="M5.8 11.3 2 22l10.7-3.79"/><path d="M4 3h.01M22 8h.01M15 2h.01M22 20h.01"/><path d="m22 2-2.24.75a2.9 2.9 0 0 0-1.96 3.12v0c.1.86-.57 1.63-1.45 1.63h-.38c-.86 0-1.6.6-1.76 1.44L14 10"/><path d="m11 13 .5 2.5L14 16l-2.5.5L11 19l-.5-2.5L8 16l2.5-.5z"/>',
}


def svg_icon(name: str, cls: str = "ico") -> str:
    body = ICONS.get(name, ICONS["wrench"])
    return (
        f'<svg class="{cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        f'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
        f"{body}</svg>"
    )


def select_options(values, selected: str = "", initial: str | None = None) -> str:
    first = f'<option value="">{esc(initial)}</option>' if initial else ""
    return first + "".join(
        f'<option value="{esc(item)}" {"selected" if item == selected else ""}>{esc(item)}</option>'
        for item in values
    )


def avatar(name: str, size: str = "", photo_url: str = "") -> str:
    if photo_url:
        src = resolve_image_url(photo_url)
        return f'<img class="avatar avatar-photo {size}" src="{esc(src)}" alt="Foto de {esc(name)}" loading="lazy">'
    initials = "".join(part[0] for part in name.split()[:2]).upper() or "OT"
    return f'<span class="avatar {size}" aria-hidden="true">{esc(initials)}</span>'


def rating_badge(rating, count: int) -> str:
    if not count:
        return '<span class="muted">Novo na plataforma</span>'
    label = "avaliação" if int(count) == 1 else "avaliações"
    return (
        f'<span class="rating">{svg_icon("star", "ico-star")} '
        f'<strong>{float(rating):.1f}</strong></span> '
        f'<span class="muted">({int(count)} {label})</span>'
    )


def professional_card(pro) -> str:
    cat_meta = CATEGORIES.get(pro["category"], {"icon": "wrench"})
    icon = svg_icon(cat_meta["icon"], "ico-cat")
    status = (
        '<span class="status"><i></i> Disponível</span>'
        if pro["available"]
        else '<span class="status busy">Agenda cheia</span>'
    )
    verified = (
        f'<span class="verified-pill" title="Identidade e dados revisados">{svg_icon("shield", "ico-xs")} Verificado</span>'
        if pro["verified"]
        else ""
    )
    if "distance" in pro.keys():
        loc = f'<span class="meta-item">{svg_icon("pin", "ico-xs")} ~{pro["distance"]:.1f} km · {esc(pro["neighborhood"])}</span>'
    else:
        loc = f'<span class="meta-item">{svg_icon("pin", "ico-xs")} {esc(pro["neighborhood"])}, Manaus</span>'
    resp = (
        f'<span class="meta-item">{svg_icon("clock", "ico-xs")} {esc(pro["response_time"])}</span>'
        if pro["response_time"]
        else ""
    )
    bio_text = pro["bio"] or "Profissional autônomo em Manaus."
    if len(bio_text) > 125:
        bio_text = bio_text[:122].rstrip() + "..."
    return f"""
    <article class="pro-card" data-pro-id="{pro['user_id']}">
      <div class="pro-top">
        <div class="pro-top-left">
          <span class="job-icon">{icon}</span>
          {verified}
        </div>
        <div class="pro-top-right">
          {status}
          <button type="button" class="fav-btn" data-fav-id="{pro['user_id']}" aria-label="Salvar {esc(pro['name'])} nos favoritos" aria-pressed="false" title="Salvar nos favoritos">
            {svg_icon("heart", "ico-sm")}
          </button>
        </div>
      </div>
      <div class="pro-person">
        {avatar(pro['name'], '', pro.get('avatar_url', '') if isinstance(pro, dict) else (pro['avatar_url'] if 'avatar_url' in pro.keys() else ''))}
        <div>
          <h3><a href="/perfil/{pro['user_id']}">{esc(pro['name'])}</a></h3>
          <p>{esc(pro['category'])}</p>
        </div>
      </div>
      <p class="pro-bio">{esc(bio_text)}</p>
      <div class="pro-meta">
        {loc}
        {resp}
        <span class="meta-item">{rating_badge(pro['rating'], pro['review_count'])}</span>
      </div>
      <div class="pro-footer">
        <span class="price-tag">{esc(pro['price_text'] or 'Orçamento sob consulta')}</span>
        <a class="button small" href="/perfil/{pro['user_id']}">Ver perfil <span aria-hidden="true">↗</span></a>
      </div>
    </article>"""


def layout_page(
    title: str,
    content: str,
    user=None,
    unread: int = 0,
    notice: str = "",
    notice_kind: str = "ok",
    og_title: str = "",
    og_desc: str = "",
    og_image: str = "",
    canonical_path: str = "",
    extra_head: str = "",
) -> str:
    if user:
        dashboard = (
            '<a href="/painel">Meu painel</a>'
            if user["role"] == "profissional"
            else '<a href="/buscar">Encontrar profissionais</a>'
        )
        unread_badge = f'<span class="count" aria-label="{unread} não lidas">{unread}</span>' if unread else ""
        auth_nav = f"""
          {dashboard}
          <a href="/conversas">Conversas {unread_badge}</a>
          {('<a href="/admin" class="nav-admin">Admin</a>') if user.get('is_admin') else ''}
          <a href="/conta">Minha conta</a>
          <form class="logout" action="/sair" method="post">
            <input type="hidden" name="csrf" value="{esc(user['csrf'])}">
            <button type="submit">Sair</button>
          </form>"""
    else:
        auth_nav = """
          <a href="/buscar">Profissionais</a>
          <a class="nav-login" href="/entrar">Entrar</a>
          <a class="button small" href="/cadastro?role=profissional">Sou profissional</a>"""

    readonly_banner = (
        '<div class="notice warn" role="status">Modo demonstração somente leitura ativo (ONDETEM_READONLY=1).</div>'
        if READ_ONLY_DEMO
        else ""
    )
    alert = (
        f'<div class="notice {esc(notice_kind)}" role="status" data-auto-dismiss>{esc(notice)}</div>'
        if notice
        else ""
    )

    return f"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{esc(title)} · OndeTem Manaus</title>
  <meta name="description" content="Encontre profissionais autônomos de manutenção e reparos avaliados em Manaus.">
  <meta name="theme-color" content="#133C55">
  <link rel="icon" type="image/svg+xml" href="/static/favicon.svg">
  <link rel="manifest" href="/manifest.webmanifest">
  <link rel="apple-touch-icon" href="/static/apple-touch-icon.png">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
  <meta name="apple-mobile-web-app-title" content="OndeTem">
  <meta property="og:type" content="website">
  <meta property="og:site_name" content="OndeTem Manaus">
  <meta property="og:title" content="{esc(og_title or (title + ' · OndeTem Manaus'))}">
  <meta property="og:description" content="{esc(og_desc or 'Encontre profissionais autônomos avaliados em Manaus com contato direto no WhatsApp.')}">
  <meta property="og:image" content="{esc(og_image or (APP_BASE_URL + '/static/og-ondetem.png'))}">
  <meta name="twitter:card" content="summary_large_image">
  {f'<link rel="canonical" href="{esc(APP_BASE_URL + canonical_path)}">' if canonical_path else ''}
  {extra_head}
  <link rel="stylesheet" href="/static/style.css">
  <script src="/static/app.js" defer></script>
</head>
<body>
  <a class="skip-link" href="#conteudo">Pular para o conteúdo principal</a>
  <header class="site-header">
    <div class="container nav">
      <a class="brand" href="/" aria-label="OndeTem: página inicial">
        <span class="brand-pin">●</span>Onde<span>Tem</span>
      </a>
      <button type="button" class="nav-toggle" data-nav-toggle aria-expanded="false" aria-controls="main-nav" aria-label="Abrir menu">
        {svg_icon("menu", "ico")}
      </button>
      <nav id="main-nav" aria-label="Navegação principal">
        <a class="nav-home" href="/#como-funciona">Como funciona</a>
        <a href="/buscar?salvos=1" class="nav-saved" data-saved-link>Salvos <span class="saved-count" data-saved-count hidden>0</span></a>
        {auth_nav}
      </nav>
    </div>
  </header>
  {readonly_banner}
  {(f'<div class="notice warn verify-banner" role="status"><span>Confirme seu e-mail para liberar avaliações.</span><form method="post" action="/reenviar-verificacao"><input type="hidden" name="csrf" value="{esc(user["csrf"])}"><button type="submit">Reenviar link</button></form></div>') if (user and not user.get('email_verified', 1)) else ''}
  {alert}
  <main id="conteudo">{content}</main>
  <footer class="footer">
    <div class="container footer-inner">
      <div>
        <a class="brand" href="/"><span class="brand-pin">●</span>Onde<span>Tem</span></a>
        <p>Conectando moradores de Manaus a profissionais autônomos avaliados no seu bairro.</p>
      </div>
      <div class="footer-meta">
        <p class="footer-links">
          <a href="/termos">Termos de Uso</a> ·
          <a href="/privacidade">Política de Privacidade (LGPD)</a>
          {(' · <a href="/conta">Minha conta e dados</a>') if user else ''}
        </p>
        <p class="lgpd-seal"><a href="/privacidade" title="Saiba como protegemos seus dados">{svg_icon("shield", "ico-xs")} Adequado à LGPD · Lei nº 13.709/2018</a></p>
      </div>
    </div>
  </footer>
  <div class="pwa-banner" id="pwa-banner" hidden>
    <div>
      <strong>Instale o OndeTem no celular</strong>
      <small>Acesso rápido direto da sua tela inicial</small>
    </div>
    <div class="pwa-banner-actions">
      <button type="button" class="button small" id="pwa-install-btn">Instalar</button>
      <button type="button" class="pwa-close" id="pwa-dismiss-btn" aria-label="Fechar">×</button>
    </div>
  </div>
  <div class="lightbox" id="lightbox" hidden role="dialog" aria-modal="true" aria-label="Visualizar foto do trabalho">
    <button type="button" class="lightbox-close" data-lightbox-close aria-label="Fechar visualização">×</button>
    <figure class="lightbox-content">
      <img src="" alt="" data-lightbox-img>
      <figcaption data-lightbox-caption></figcaption>
    </figure>
  </div>
</body>
</html>"""


def home_view(db: sqlite3.Connection, pros_featured: list, stats: dict) -> str:
    cat_tabs = (
        '<div class="cat-tabs" role="tablist" aria-label="Áreas de atuação">'
        '<button type="button" class="cat-tab active" data-cat-tab="all" role="tab" aria-selected="true">Todas (24)</button>'
        + "".join(
            f'<button type="button" class="cat-tab" data-cat-tab="{esc(grp)}" role="tab" aria-selected="false">{esc(grp)}</button>'
            for grp in CATEGORY_GROUPS
        )
        + "</div>"
    )
    category_cards = "".join(
        f"""<a class="category" data-cat-group="{esc(meta['group'])}" href="/buscar?{urlencode({'categoria': cat})}">
              <span class="cat-icon-wrap">{svg_icon(meta['icon'], 'ico-cat')}</span>
              <strong>{esc(cat)}</strong>
              <span class="cat-sub">{esc(meta['short'])}</span>
              <small>Explorar ↗</small>
            </a>"""
        for cat, meta in CATEGORIES.items()
    )
    cards_html = "".join(professional_card(pro) for pro in pros_featured)
    return f"""
    <section class="hero">
      <div class="container hero-grid">
        <div class="hero-copy">
          <span class="eyebrow">{svg_icon('pin', 'ico-xs')} FEITO PARA MANAUS · AM</span>
          <h1>Precisou de um profissional? <em>Aqui você encontra.</em></h1>
          <p>Encontre eletricistas, diaristas, mecânicos, técnicos de TI, contadores, músicos e outros profissionais avaliados no seu bairro, com contato direto via WhatsApp ou chat.</p>
          <form class="search-box" action="/buscar" method="get" role="search">
            <label>
              <span>Qual serviço você precisa?</span>
              <input name="q" placeholder="Ex.: confeiteira, diarista, mecânico, TI, músico..." aria-label="Qual serviço você precisa?">
            </label>
            <label>
              <span>Em qual bairro?</span>
              <select name="bairro" aria-label="Em qual bairro?">{select_options(NEIGHBORHOODS, initial='Todos os bairros de Manaus')}</select>
            </label>
            <button class="button" type="submit">{svg_icon('search', 'ico-sm')} Encontrar</button>
          </form>
          <div class="hero-foot">
            <span>{svg_icon('check', 'ico-xs')} Avaliações reais de clientes</span>
            <span>{svg_icon('check', 'ico-xs')} Contato direto no WhatsApp</span>
            <span>{svg_icon('check', 'ico-xs')} Sem intermediários</span>
          </div>
        </div>
        <div class="hero-art" aria-hidden="true">
          <div class="art-orbit"></div>
          <div class="art-card art-card-a">
            <span class="mini-icon">{svg_icon('bolt', 'ico-sm')}</span>
            <div><b>Carlos Silva · Eletricista</b><small>Ponta Negra · Responde em 15 min</small></div>
            <span class="mini-star">★ 5,0</span>
          </div>
          <div class="art-house">
            <div class="house-roof"></div>
            <div class="house-body">
              <div class="house-window">✦</div>
              <div class="house-door"></div>
            </div>
          </div>
          <div class="art-card art-card-b">
            <span class="mini-avatar">MC</span>
            <div><b>Marina Costa · Ar-condicionado</b><small>Parque Dez · Perfil verificado</small></div>
            <span class="mini-pill">Disponível</span>
          </div>
          <div class="art-location">{svg_icon('pin', 'ico-xs')} {stats['neighborhoods']} bairros em Manaus</div>
        </div>
      </div>
    </section>

    <section class="trust-strip">
      <div class="container trust-grid">
        <div><strong>{stats['pros']}+</strong><span>Profissionais cadastrados</span></div>
        <div><strong>{stats['reviews']}+</strong><span>Avaliações verificadas</span></div>
        <div><strong>{stats['avg_rating']:.1f} ★</strong><span>Nota média dos serviços</span></div>
        <div><strong>{stats['neighborhoods']}</strong><span>Bairros cobertos em Manaus</span></div>
      </div>
    </section>

    <section class="section container" id="categorias">
      <div class="section-heading">
        <div>
          <span class="eyebrow">CATEGORIAS POPULARES</span>
          <h2>24 áreas de serviços em Manaus</h2>
        </div>
        <a href="/buscar" class="text-link">Ver todos os profissionais ↗</a>
      </div>
      {cat_tabs}
      <div class="category-grid" data-cat-grid>{category_cards}</div>
    </section>

    <section class="section section-tint" id="profissionais">
      <div class="container">
        <div class="section-heading">
          <div>
            <span class="eyebrow">DESTAQUES EM MANAUS</span>
            <h2>Profissionais bem avaliados perto de você</h2>
            <p>Compare portfólio, nota dos clientes e tempo médio de resposta antes de chamar.</p>
          </div>
          <a class="text-link" href="/buscar">Explorar busca completa ↗</a>
        </div>
        <div class="card-grid">{cards_html}</div>
      </div>
    </section>

    <section class="section container" id="como-funciona">
      <div class="section-heading">
        <div>
          <span class="eyebrow">SIMPLES E DIRETO</span>
          <h2>Do problema à solução em 3 passos</h2>
        </div>
      </div>
      <div class="steps">
        <div>
          <b>01</b>
          <h3>Busque por serviço ou bairro</h3>
          <p>Filtre por categoria, bairro de Manaus, nota mínima ou ordene por proximidade.</p>
        </div>
        <div>
          <b>02</b>
          <h3>Compare avaliações e portfólio</h3>
          <p>Veja comentários de moradores, fotos reais de serviços concluídos e preço inicial.</p>
        </div>
        <div>
          <b>03</b>
          <h3>Combine direto sem burocracia</h3>
          <p>Chame pelo WhatsApp com mensagem pronta ou converse pelo chat interno do OndeTem.</p>
        </div>
      </div>
    </section>

    <section class="join container">
      <div>
        <span class="eyebrow">TRABALHA POR CONTA PRÓPRIA EM MANAUS?</span>
        <h2>Mostre seu trabalho e conquiste novos clientes no seu bairro.</h2>
        <p>Crie seu perfil gratuito, adicione fotos dos seus serviços e receba contatos diretos.</p>
      </div>
      <a class="button light" href="/cadastro?role=profissional">Criar perfil profissional ↗</a>
    </section>"""


def search_view(found: list, filters: dict) -> str:
    q = filters["q"]
    category = filters["categoria"]
    neighborhood = filters["bairro"]
    sort_by = filters["ordenar"]
    only_avail = filters["disponivel"]
    min_rating = filters["nota"]
    has_geo = filters["has_geo"]
    saved_mode = filters["salvos"]

    chips = []
    if q:
        chips.append(f'<span class="chip">Busca: "{esc(q)}"</span>')
    if category:
        chips.append(f'<span class="chip">Categoria: {esc(category)}</span>')
    if neighborhood:
        chips.append(f'<span class="chip">Bairro: {esc(neighborhood)}</span>')
    if only_avail:
        chips.append('<span class="chip">Apenas disponíveis</span>')
    if min_rating:
        chips.append(f'<span class="chip">Nota {esc(min_rating)}+ ★</span>')
    if has_geo:
        chips.append('<span class="chip">Ordenado por proximidade</span>')
    if saved_mode:
        chips.append('<span class="chip">Apenas salvos por você</span>')

    chips_html = ""
    if chips:
        chips_html = (
            '<div class="active-chips">'
            + "".join(chips)
            + '<a class="chip-clear" href="/buscar">Limpar tudo</a></div>'
        )

    sort_options = [
        ("relevancia", "Relevância e disponibilidade"),
        ("nota", "Melhor avaliados"),
        ("avaliacoes", "Mais avaliados"),
    ]
    if has_geo:
        sort_options.insert(0, ("proximidade", "Mais próximos de você"))

    sort_html = "".join(
        f'<option value="{val}" {"selected" if sort_by == val else ""}>{label}</option>'
        for val, label in sort_options
    )

    rating_opts = "".join(
        f'<option value="{v}" {"selected" if min_rating == v else ""}>{lbl}</option>'
        for v, lbl in [("", "Qualquer nota"), ("4", "4,0 estrelas ou mais"), ("4.5", "4,5 estrelas ou mais")]
    )

    if found:
        cards = "".join(professional_card(pro) for pro in found)
    else:
        cards = f"""
        <div class="empty">
          <span class="empty-ico">{svg_icon('search', 'ico-lg')}</span>
          <h3>Nenhum profissional encontrado</h3>
          <p>Tente remover algum filtro ou buscar por outra palavra-chave.</p>
          <a href="/buscar" class="button small">Limpar filtros</a>
        </div>"""

    count_label = "profissional encontrado" if len(found) == 1 else "profissionais encontrados"
    saved_attr = ' data-saved-mode="1"' if saved_mode else ""

    return f"""
    <section class="page-hero">
      <div class="container">
        <span class="eyebrow">BUSCA INTELIGENTE · MANAUS</span>
        <h1>{'Seus profissionais salvos' if saved_mode else 'Profissionais em Manaus'}</h1>
        <p>Compare avaliações, tempo de resposta e disponibilidade antes de pedir orçamento.</p>
      </div>
    </section>

    <div class="container search-layout">
      <aside class="filters" aria-label="Filtros de busca">
        <h2>Filtrar resultados</h2>
        <form action="/buscar" method="get">
          <label>Serviço, nome ou especialidade
            <input name="q" value="{esc(q)}" placeholder="Ex.: disjuntor, split, vazamento">
          </label>
          <label>Categoria
            <select name="categoria">{select_options(CATEGORIES, category, initial='Todas as categorias')}</select>
          </label>
          <label>Bairro
            <select name="bairro">{select_options(NEIGHBORHOODS, neighborhood, initial='Todos os bairros')}</select>
          </label>
          <label>Nota mínima
            <select name="nota">{rating_opts}</select>
          </label>
          <label>Ordenar por
            <select name="ordenar">{sort_html}</select>
          </label>
          <label class="checkbox">
            <input type="checkbox" name="disponivel" value="1" {'checked' if only_avail else ''}>
            Apenas disponíveis agora
          </label>
          <button class="button wide" type="submit">Aplicar filtros</button>
        </form>
        <button class="location-button" type="button" data-near>
          {svg_icon('target', 'ico-sm')} Usar minha localização
        </button>
        <p class="hint" data-location-status>Usamos sua localização apenas nesta busca para estimar a distância.</p>
      </aside>

      <div class="results"{saved_attr}>
        <div class="results-head">
          <div>
            <h2 data-results-count>{len(found)} {count_label}</h2>
            <p>{'Ordenados por distância aproximada.' if has_geo else 'Busca tolerante a acentos ativa.'}</p>
          </div>
          <span class="badge">{svg_icon('pin', 'ico-xs')} Manaus · AM</span>
        </div>
        {chips_html}
        <div class="card-grid" data-results-grid>{cards}</div>
      </div>
    </div>"""


def profile_view(db: sqlite3.Connection, pro, user) -> str:
    works = db.execute(
        "SELECT * FROM works WHERE professional_id = ? ORDER BY id DESC",
        (pro["user_id"],),
    ).fetchall()
    reviews = db.execute(
        """SELECT r.*, u.name FROM reviews r
           JOIN users u ON u.id = r.client_id
           WHERE r.professional_id = ? ORDER BY r.created_at DESC""",
        (pro["user_id"],),
    ).fetchall()

    # Distribuição de notas (5 a 1 estrela)
    counts = {i: 0 for i in range(1, 6)}
    for r in reviews:
        counts[int(r["rating"])] += 1
    total_rev = len(reviews)

    breakdown_rows = ""
    for star_n in range(5, 0, -1):
        pct = round((counts[star_n] / total_rev) * 100) if total_rev else 0
        breakdown_rows += f"""
          <div class="bar-row">
            <span>{star_n} ★</span>
            <div class="bar-track"><div class="bar-fill" style="width:{pct}%"></div></div>
            <small>{counts[star_n]}</small>
          </div>"""

    rating_summary = ""
    if total_rev:
        rating_summary = f"""
        <div class="rating-summary">
          <div class="rating-big">
            <strong>{float(pro['rating']):.1f}</strong>
            <span class="rating">{'★' * round(float(pro['rating']))}</span>
            <small>{total_rev} {'avaliação' if total_rev == 1 else 'avaliações'}</small>
          </div>
          <div class="rating-bars">{breakdown_rows}</div>
        </div>"""

    gallery = "".join(
        f"""<figure class="work" data-lightbox-src="{esc(resolve_image_url(w['image']))}" data-lightbox-text="{esc(w['caption'])}" tabindex="0" role="button" aria-label="Ampliar foto: {esc(w['caption'])}">
              <img src="{esc(resolve_image_url(w['image']))}" alt="{esc(w['caption'])}" loading="lazy">
              <figcaption>{esc(w['caption'])}</figcaption>
            </figure>"""
        for w in works
    )

    reviews_html = "".join(
        f"""<article class="review">
              <div class="review-top">
                <div class="review-author">
                  {avatar(r['name'], 'tiny')}
                  <div>
                    <b>{esc(r['name'])}</b>
                    <small>{esc(format_manaus_date(r['created_at']))}</small>
                  </div>
                </div>
                <span class="rating" aria-label="{r['rating']} de 5 estrelas">{'★' * int(r['rating'])}{'☆' * (5 - int(r['rating']))}</span>
              </div>
              <p>{esc(r['comment'])}</p>
            </article>"""
        for r in reviews
    ) or '<p class="muted">Este profissional ainda não recebeu avaliações. Seja o primeiro a avaliar após o serviço!</p>'

    wa_url = whatsapp_link(pro["whatsapp"], pro["name"], pro["category"])
    wa_btn = (
        f'<a class="button whatsapp wide" href="/contato/whatsapp/{pro["user_id"]}" target="_blank" rel="noopener noreferrer">'
        f'{svg_icon("whatsapp", "ico-sm")} Chamar no WhatsApp</a>'
        if wa_url
        else ""
    )

    if user and user["role"] == "cliente":
        chat_action = f"""
        <form action="/iniciar/{pro['user_id']}" method="post">
          <input type="hidden" name="csrf" value="{esc(user['csrf'])}">
          <button class="button {'secondary ' if wa_btn else ''}wide" type="submit">
            {svg_icon('chat', 'ico-sm')} Conversar pelo chat interno
          </button>
        </form>"""
        review_form = f"""
        <form class="review-form" action="/avaliar/{pro['user_id']}" method="post">
          <input type="hidden" name="csrf" value="{esc(user['csrf'])}">
          <h3>Deixe sua avaliação</h3>
          <fieldset class="star-picker">
            <legend>Sua nota</legend>
            <div class="star-inputs">
              {''.join(f'<input type="radio" id="star-{n}" name="rating" value="{n}" {"checked" if n == 5 else ""}><label for="star-{n}" title="{n} estrela{"s" if n > 1 else ""}">★</label>' for n in range(5, 0, -1))}
            </div>
          </fieldset>
          <label>Como foi o atendimento?
            <textarea name="comment" maxlength="500" required placeholder="Conte sobre pontualidade, qualidade do serviço e preço..."></textarea>
          </label>
          <button class="button small" type="submit">Publicar avaliação</button>
        </form>"""
    elif user and user["id"] == pro["user_id"]:
        chat_action = '<a class="button wide" href="/painel">Editar meu perfil ↗</a>'
        review_form = ""
    else:
        login_url = "/entrar?" + urlencode({"next": f"/perfil/{pro['user_id']}"})
        chat_action = (
            f'<a class="button {"secondary " if wa_btn else ""}wide" href="{login_url}">'
            f'{svg_icon("chat", "ico-sm")} Entrar para conversar</a>'
            if not user
            else '<p class="hint">Entre com uma conta de cliente para iniciar chat ou avaliar.</p>'
        )
        review_form = ""

    verified_tag = (
        f'<span class="verified-pill">{svg_icon("shield", "ico-xs")} Perfil verificado</span>'
        if pro["verified"]
        else ""
    )

    return f"""
    <section class="page-hero">
      <div class="container profile-hero-bar">
        <a href="/buscar" class="back-link">← Voltar à busca</a>
        <div class="profile-hero-actions">
          <button type="button" class="icon-pill" data-fav-id="{pro['user_id']}" aria-pressed="false">
            {svg_icon('heart', 'ico-xs')} <span>Salvar</span>
          </button>
          <button type="button" class="icon-pill" data-share-profile data-share-title="{esc(pro['name'])} · {esc(pro['category'])} no OndeTem">
            {svg_icon('share', 'ico-xs')} <span>Compartilhar</span>
          </button>
        </div>
      </div>
    </section>

    <div class="container profile">
      <div class="profile-main">
        <div class="profile-title">
          {avatar(pro['name'], 'large', pro.get('avatar_url', '') if isinstance(pro, dict) else (pro['avatar_url'] if 'avatar_url' in pro.keys() else ''))}
          <div>
            <div class="profile-badges">
              <span class="eyebrow">{esc(pro['category'])}</span>
              {verified_tag}
            </div>
            <h1>{esc(pro['name'])}</h1>
            <p class="profile-sub">
              {svg_icon('pin', 'ico-xs')} {esc(pro['neighborhood'])}, Manaus · {rating_badge(pro['rating'], pro['review_count'])}
            </p>
          </div>
        </div>

        <section class="profile-section">
          <h2>Sobre o profissional</h2>
          <p>{esc(pro['bio'] or 'Apresentação em breve.')}</p>
        </section>

        <section class="profile-section">
          <h2>Experiência e qualificações</h2>
          <p>{esc(pro['experience'] or 'Informações em breve.')}</p>
        </section>

        <section class="profile-section">
          <h2>Portfólio de trabalhos realizados</h2>
          <p class="hint">Clique em qualquer imagem para ampliar.</p>
          <div class="gallery">{gallery or '<p class="muted">Ainda não há fotos neste portfólio.</p>'}</div>
        </section>

        <section class="profile-section" id="avaliacoes">
          <h2>Avaliações dos clientes</h2>
          {rating_summary}
          {reviews_html}
          {review_form}
        </section>
      </div>

      <aside class="contact-card">
        <span class="eyebrow">ORÇAMENTO DIRETO</span>
        <h2>Fale com {esc(pro['name'].split()[0])}</h2>
        <p>Combine detalhes, horário e valor diretamente com o profissional.</p>
        <div class="contact-line"><span>Serviço</span><b>{esc(pro['category'])}</b></div>
        <div class="contact-line"><span>Preço inicial</span><b>{esc(pro['price_text'] or 'Sob consulta')}</b></div>
        <div class="contact-line"><span>Tempo de resposta</span><b>{esc(pro['response_time'] or 'No mesmo dia')}</b></div>
        <div class="contact-line">
          <span>Disponibilidade</span>
          <b class="{'text-ok' if pro['available'] else 'text-warn'}">{'Disponível agora' if pro['available'] else 'Agenda cheia'}</b>
        </div>
        {f'<div class="contact-line"><span>WhatsApp</span><b>{esc(format_phone_display(pro["whatsapp"]))}</b></div>' if pro['whatsapp'] else ''}
        <div class="contact-actions">
          {wa_btn}
          {chat_action}
        </div>
        <small>Dica de segurança: sempre peça orçamento detalhado antes do início do serviço.</small>
      </aside>
    </div>"""


def auth_view(role: str = "cliente", login: bool = False, next_path: str = "", error: str = "") -> str:
    error_html = f'<p class="form-error" role="alert">{esc(error)}</p>' if error else ""
    if login:
        title = "Que bom ver você de novo."
        subtitle = "Acesse sua conta para conversar, avaliar ou gerenciar seu perfil."
        action = "/entrar"
        content = f"""
          <label>E-mail
            <input type="email" name="email" id="login-email" autocomplete="email" required>
          </label>
          <label>Senha
            <input type="password" name="password" id="login-password" autocomplete="current-password" required>
          </label>
          <div class="auth-forgot"><a href="/esqueci-senha">Esqueci minha senha</a></div>
          <input type="hidden" name="next" value="{esc(next_path)}">
          <button class="button wide" type="submit">Entrar</button>
          <div class="demo-box">
            <span>Acesso rápido para demonstração:</span>
            <div class="demo-btns">
              <button type="button" class="demo-fill" data-fill-email="cliente@ondetem.local" data-fill-pass="Demo123!">Cliente Demo</button>
              <button type="button" class="demo-fill" data-fill-email="carlos@ondetem.local" data-fill-pass="Demo123!">Profissional Demo</button>
            </div>
          </div>
          <p class="auth-switch">Não tem conta? <a href="/cadastro">Cadastre-se gratuitamente</a></p>"""
    else:
        title = "Faça parte do OndeTem."
        ts_key = turnstile_site_key()
        if ts_key:
            antibot_html = (
                f'<script src="https://challenges.cloudflare.com/turnstile/v0/api.js" async defer></script>'
                f'<div class="cf-turnstile" data-sitekey="{esc(ts_key)}"></div>'
            )
        else:
            q_math, tok_math = generate_math_challenge()
            antibot_html = (
                f'<div class="antibot-box">'
                f'<label>Verificação anti-robô: <strong>{esc(q_math)}</strong>'
                f'<input type="number" name="captcha_answer" inputmode="numeric" required placeholder="Digite o resultado">'
                f'</label>'
                f'<input type="hidden" name="captcha_token" value="{esc(tok_math)}">'
                f'</div>'
            )
        subtitle = "Escolha como deseja usar a plataforma em Manaus."
        action = "/cadastro"
        extra = f"""
          <div class="pro-fields">
            <label>Principal serviço
              <select name="category">{select_options(CATEGORIES)}</select>
            </label>
            <label>Bairro de atuação
              <select name="neighborhood">{select_options(NEIGHBORHOODS)}</select>
            </label>
            <label>WhatsApp (com DDD 92)
              <input name="whatsapp" inputmode="tel" maxlength="20" placeholder="(92) 99999-9999">
            </label>
          </div>"""
        content = f"""
          <div class="role-picker">
            <label><input type="radio" name="role" value="cliente" {'checked' if role != 'profissional' else ''}> Busco um profissional</label>
            <label><input type="radio" name="role" value="profissional" {'checked' if role == 'profissional' else ''}> Ofereço serviços</label>
          </div>
          <label>Nome completo
            <input name="name" autocomplete="name" maxlength="80" required placeholder="Ex.: Maria Oliveira">
          </label>
          <label>E-mail
            <input type="email" name="email" autocomplete="email" required placeholder="voce@exemplo.com">
          </label>
          <label>Senha (mínimo de 8 caracteres)
            <input type="password" name="password" minlength="8" autocomplete="new-password" required>
          </label>
          {extra}
          <div class="hp-field" aria-hidden="true">
            <label>Não preencha este campo<input type="text" name="website_url" tabindex="-1" autocomplete="off"></label>
          </div>
          {antibot_html}
          <label class="checkbox terms-check">
            <input type="checkbox" name="accept_terms" value="1" required>
            <span>Li e concordo com os <a href="/termos" target="_blank">Termos de Uso</a> e a <a href="/privacidade" target="_blank">Política de Privacidade (LGPD)</a>.</span>
          </label>
          <button class="button wide" type="submit">Criar conta</button>
          <p class="auth-switch">Já tem conta? <a href="/entrar">Entrar agora</a></p>"""

    return f"""
    <section class="auth-bg">
      <div class="auth-card">
        <a href="/" class="brand"><span class="brand-pin">●</span>Onde<span>Tem</span></a>
        <span class="eyebrow">MANAUS EM BOAS MÃOS</span>
        <h1>{title}</h1>
        <p>{subtitle}</p>
        {error_html}
        <form class="stack-form" method="post" action="{action}">{content}</form>
      </div>
    </section>"""


def dashboard_view(db: sqlite3.Connection, user, unread: int) -> str:
    pro = db.execute("SELECT * FROM professionals WHERE user_id = ?", (user["id"],)).fetchone()
    works = db.execute("SELECT * FROM works WHERE professional_id = ? ORDER BY id DESC", (user["id"],)).fetchall()
    rev_stats = db.execute(
        "SELECT COUNT(*) AS cnt, COALESCE(AVG(rating), 0) AS avg FROM reviews WHERE professional_id = ?",
        (user["id"],),
    ).fetchone()

    # Cálculo de completude do perfil para orientar o profissional
    checks = [
        bool(pro["bio"].strip()),
        bool(pro["experience"].strip()),
        bool(pro["price_text"].strip()),
        bool(pro["whatsapp"].strip()),
        len(works) > 0,
    ]
    completeness = int(round((sum(checks) / len(checks)) * 100))

    csrf = esc(user["csrf"])
    gallery = "".join(
        f"""<figure class="work work-manage">
              <img src="{esc(resolve_image_url(w['image']))}" alt="{esc(w['caption'])}" loading="lazy">
              <figcaption>
                <span>{esc(w['caption'])}</span>
                <form action="/portfolio/remover/{w['id']}" method="post" data-confirm="Remover esta foto do portfólio?">
                  <input type="hidden" name="csrf" value="{csrf}">
                  <button type="submit" class="trash-btn" title="Remover foto" aria-label="Remover foto">{svg_icon('trash', 'ico-xs')}</button>
                </form>
              </figcaption>
            </figure>"""
        for w in works
    )

    if pro["verified"]:
        cpf_box = '<p class="verified-pill">✓ Seu perfil já possui o selo Verificado ativo!</p>'
    elif (pro["verification_status"] if "verification_status" in pro.keys() else "") == "pending":
        cpf_box = (
            f'<p class="notice warn" style="border-radius:10px;text-align:left;padding:12px;">'
            f'Solicitação em análise pelo administrador (CPF {esc(pro["cpf_masked"] if "cpf_masked" in pro.keys() else "")}). '
            f'Assim que aprovada, o selo Verificado aparecerá no seu perfil.</p>'
        )
    else:
        cpf_box = f"""<p>Aumente a confiança dos moradores de Manaus solicitando o selo <strong>Verificado</strong>. Pela LGPD, seu CPF é validado e convertido em <strong>hash criptográfico</strong> — nunca salvamos o número aberto nem exibimos no seu perfil.</p>
          <form class="stack-form" action="/perfil/verificar-cpf" method="post">
            <input type="hidden" name="csrf" value="{csrf}">
            <label>CPF do titular (somente números ou 000.000.000-00)
              <input name="cpf" inputmode="numeric" maxlength="14" required placeholder="000.000.000-00">
            </label>
            <label class="checkbox terms-check">
              <input type="checkbox" name="cpf_consent" value="1" required>
              <span>Autorizo o uso exclusivo do meu CPF para validação de identidade e prevenção a fraudes, conforme a <a href="/privacidade" target="_blank">Política de Privacidade (LGPD)</a>.</span>
            </label>
            <button class="button small" type="submit">Solicitar selo Verificado</button>
          </form>"""

    return f"""
    <section class="page-hero">
      <div class="container">
        <span class="eyebrow">PAINEL DO PROFISSIONAL</span>
        <h1>Olá, {esc(user['name'].split()[0])}!</h1>
        <p>Mantenha seu perfil completo e atualizado para aparecer no topo das buscas em Manaus.</p>
      </div>
    </section>

    <div class="container kpi-row">
      <div class="kpi-card"><span>Nota média</span><strong>{float(rev_stats['avg']):.1f} ★</strong></div>
      <div class="kpi-card"><span>Avaliações</span><strong>{int(rev_stats['cnt'])}</strong></div>
      <div class="kpi-card"><span>Cliques no WhatsApp</span><strong>{int(pro['whatsapp_clicks'] or 0)}</strong></div>
      <div class="kpi-card">
        <span>Força do perfil</span>
        <strong>{completeness}%</strong>
        <div class="bar-track"><div class="bar-fill" style="width:{completeness}%"></div></div>
      </div>
    </div>

    <div class="container dashboard">
      <div class="panel">
        <h2>Editar informações públicas</h2>
        <form action="/perfil/editar" method="post" class="stack-form">
          <input type="hidden" name="csrf" value="{csrf}">
          <div class="form-row">
            <label>Serviço principal
              <select name="category" required>{select_options(CATEGORIES, pro['category'])}</select>
            </label>
            <label>Bairro de atuação
              <select name="neighborhood" required>{select_options(NEIGHBORHOODS, pro['neighborhood'])}</select>
            </label>
          </div>
          <div class="form-row">
            <label>WhatsApp (com DDD)
              <input name="whatsapp" inputmode="tel" maxlength="20" value="{esc(format_phone_display(pro['whatsapp']))}" placeholder="(92) 99999-9999">
            </label>
            <label>Tempo médio de resposta
              <select name="response_time">{select_options(RESPONSE_TIMES, pro['response_time'])}</select>
            </label>
          </div>
          <label>Sobre mim e serviços oferecidos
            <textarea name="bio" maxlength="800" required>{esc(pro['bio'])}</textarea>
          </label>
          <label>Experiência e qualificações
            <textarea name="experience" maxlength="600">{esc(pro['experience'])}</textarea>
          </label>
          <label>Preço inicial ou forma de orçamento
            <input name="price_text" maxlength="100" value="{esc(pro['price_text'])}" placeholder="Ex.: Visita técnica a partir de R$ 80">
          </label>
          <label class="checkbox">
            <input type="checkbox" name="available" value="1" {'checked' if pro['available'] else ''}>
            Disponível para novos serviços agora
          </label>
          <button class="button" type="submit">Salvar alterações</button>
        </form>
      </div>

      <div>
        <div class="panel">
          <h2>Foto de perfil</h2>
          <div class="avatar-upload-row">
            {avatar(user['name'], 'large', pro['avatar_url'] if 'avatar_url' in pro.keys() else '')}
            <form class="stack-form" action="/perfil/foto" method="post" enctype="multipart/form-data">
              <input type="hidden" name="csrf" value="{csrf}">
              <label>Escolha uma foto nítida do seu rosto (JPG, PNG ou WEBP)
                <input type="file" name="avatar" accept="image/jpeg,image/png,image/webp" required>
              </label>
              <button class="button small" type="submit">Atualizar foto de perfil</button>
            </form>
          </div>
        </div>

        <div class="panel">
          <h2>Portfólio de trabalhos ({len(works)}/12)</h2>
          <p>Fotos reais de serviços concluídos aumentam a confiança dos clientes.</p>
          <div class="gallery dashboard-gallery">{gallery or '<p class="muted">Nenhuma foto cadastrada ainda.</p>'}</div>
          <form class="stack-form" action="/portfolio/adicionar" method="post" enctype="multipart/form-data">
            <input type="hidden" name="csrf" value="{csrf}">
            <label>Legenda do serviço
              <input name="caption" maxlength="100" required placeholder="Ex.: Instalação de split 12.000 BTUs">
            </label>
            <label>Foto (JPG, PNG ou WEBP; até 3 MB — metadados EXIF removidos automaticamente)
              <input type="file" name="image" accept="image/jpeg,image/png,image/webp" required>
            </label>
            <button class="button small" type="submit">Adicionar ao portfólio</button>
          </form>
        </div>

        <div class="panel">
          <h2>Selo de Identidade Verificada (CPF)</h2>
          {cpf_box}
        </div>

        <div class="panel">
          <h2>Visualizar como cliente</h2>
          <p>Veja exatamente como os moradores de Manaus encontram o seu perfil.</p>
          <a class="text-link" href="/perfil/{user['id']}">Abrir meu perfil público ↗</a>
        </div>
      </div>
    </div>"""


def conversations_view(db: sqlite3.Connection, user) -> str:
    rows = db.execute(
        """SELECT c.id, u.name, p.category,
           (SELECT body FROM messages m WHERE m.conversation_id = c.id ORDER BY m.id DESC LIMIT 1) AS last_body,
           (SELECT created_at FROM messages m WHERE m.conversation_id = c.id ORDER BY m.id DESC LIMIT 1) AS last_at,
           (SELECT COUNT(*) FROM messages m WHERE m.conversation_id = c.id AND m.sender_id <> ? AND m.read_at IS NULL) AS unread
           FROM conversations c
           JOIN users u ON u.id = CASE WHEN c.client_id = ? THEN c.professional_id ELSE c.client_id END
           JOIN professionals p ON p.user_id = c.professional_id
           WHERE c.client_id = ? OR c.professional_id = ?
           ORDER BY COALESCE(last_at, c.created_at) DESC""",
        (user["id"], user["id"], user["id"], user["id"]),
    ).fetchall()

    items = "".join(
        f"""<a class="conversation-item" href="/conversa/{r['id']}">
              {avatar(r['name'])}
              <span>
                <b>{esc(r['name'])}</b>
                <small>{esc(r['category'])} · {esc((r['last_body'] or 'Inicie a conversa')[:80])}</small>
              </span>
              <div class="conv-right">
                <time>{esc(format_manaus_time(r['last_at']) if r['last_at'] else '')}</time>
                {f'<i class="unread">{r["unread"]}</i>' if r['unread'] else '<span aria-hidden="true">→</span>'}
              </div>
            </a>"""
        for r in rows
    )
    if not items:
        items = f"""
        <div class="empty">
          <span class="empty-ico">{svg_icon('chat', 'ico-lg')}</span>
          <h3>Nenhuma conversa ainda</h3>
          <p>Encontre um profissional em Manaus e envie uma mensagem para pedir orçamento.</p>
          <a class="button small" href="/buscar">Encontrar profissionais</a>
        </div>"""

    return f"""
    <section class="page-hero">
      <div class="container">
        <span class="eyebrow">MENSAGENS DIRETAS</span>
        <h1>Suas conversas</h1>
      </div>
    </section>
    <div class="container narrow panel conversation-list">{items}</div>"""


def chat_view(db: sqlite3.Connection, user, conversation) -> str:
    other_id = conversation["professional_id"] if user["id"] == conversation["client_id"] else conversation["client_id"]
    other = db.execute("SELECT name FROM users WHERE id = ?", (other_id,)).fetchone()
    rows = db.execute(
        "SELECT * FROM messages WHERE conversation_id = ? ORDER BY id ASC",
        (conversation["id"],),
    ).fetchall()

    bubbles = "".join(
        f"""<div class="bubble {'mine' if m['sender_id'] == user['id'] else 'theirs'}">
              <p>{esc(m['body'])}</p>
              <small>{esc(format_manaus_time(m['created_at']))}</small>
            </div>"""
        for m in rows
    )

    quick_templates = ""
    if user["role"] == "cliente" and not rows:
        quick_templates = """
        <div class="quick-replies">
          <button type="button" data-quick-msg="Olá! Gostaria de solicitar um orçamento. Você tem disponibilidade esta semana?">Pedir orçamento</button>
          <button type="button" data-quick-msg="Boa tarde! Você atende no meu bairro hoje?">Consultar disponibilidade</button>
        </div>"""

    return f"""
    <section class="page-hero">
      <div class="container">
        <a class="back-link" href="/conversas">← Todas as conversas</a>
      </div>
    </section>
    <div class="container narrow chat-panel">
      <div class="chat-head">
        {avatar(other['name'])}
        <div>
          <h1>{esc(other['name'])}</h1>
          <p>Horários exibidos no fuso de Manaus (AMT)</p>
        </div>
      </div>
      <div class="chat-messages" data-chat-scroll>
        {bubbles or '<p class="muted">Envie a primeira mensagem para iniciar o atendimento.</p>'}
      </div>
      {quick_templates}
      <form class="chat-compose" action="/conversa/{conversation['id']}" method="post">
        <input type="hidden" name="csrf" value="{esc(user['csrf'])}">
        <label class="sr-only" for="message">Mensagem</label>
        <textarea id="message" name="body" maxlength="1500" required placeholder="Escreva sua mensagem... (Ctrl+Enter para enviar)"></textarea>
        <button class="button" type="submit">Enviar ↗</button>
      </form>
    </div>"""


def forgot_password_view(error: str = "", sent: bool = False) -> str:
    error_html = f'<p class="form-error" role="alert">{esc(error)}</p>' if error else ""
    if sent:
        body = """
        <div class="legal-box ok-box">
          <h3>Verifique sua caixa de entrada</h3>
          <p>Se existir uma conta cadastrada com este e-mail, enviamos um link seguro para redefinir sua senha. O link expira em <strong>30 minutos</strong>.</p>
          <p class="hint">Não encontrou? Confira também a pasta de Spam ou Lixo Eletrônico.</p>
        </div>
        <p class="auth-switch"><a href="/entrar">← Voltar para o login</a></p>"""
    else:
        body = f"""
        {error_html}
        <form class="stack-form" method="post" action="/esqueci-senha">
          <label>E-mail cadastrado
            <input type="email" name="email" autocomplete="email" required placeholder="voce@exemplo.com">
          </label>
          <button class="button wide" type="submit">Enviar link de redefinição</button>
          <p class="auth-switch"><a href="/entrar">← Voltar para o login</a></p>
        </form>"""
    return f"""
    <section class="auth-bg">
      <div class="auth-card">
        <a href="/" class="brand"><span class="brand-pin">●</span>Onde<span>Tem</span></a>
        <span class="eyebrow">RECUPERAÇÃO DE ACESSO</span>
        <h1>Esqueceu sua senha?</h1>
        <p>Informe seu e-mail para receber um link seguro de redefinição.</p>
        {body}
      </div>
    </section>"""


def reset_password_view(token: str = "", error: str = "", invalid: bool = False) -> str:
    error_html = f'<p class="form-error" role="alert">{esc(error)}</p>' if error else ""
    if invalid:
        body = """
        <p class="form-error" role="alert">Este link de redefinição é inválido, já foi usado ou expirou.</p>
        <a class="button wide" href="/esqueci-senha">Solicitar novo link</a>"""
    else:
        body = f"""
        {error_html}
        <form class="stack-form" method="post" action="/redefinir-senha">
          <input type="hidden" name="token" value="{esc(token)}">
          <label>Nova senha (mínimo de 8 caracteres)
            <input type="password" name="password" minlength="8" autocomplete="new-password" required>
          </label>
          <label>Confirmar nova senha
            <input type="password" name="confirm_password" minlength="8" autocomplete="new-password" required>
          </label>
          <button class="button wide" type="submit">Salvar nova senha</button>
        </form>"""
    return f"""
    <section class="auth-bg">
      <div class="auth-card">
        <a href="/" class="brand"><span class="brand-pin">●</span>Onde<span>Tem</span></a>
        <span class="eyebrow">NOVA SENHA</span>
        <h1>Criar nova senha</h1>
        <p>Escolha uma senha forte que você não use em outros sites.</p>
        {body}
      </div>
    </section>"""


def terms_view() -> str:
    return """
    <section class="page-hero">
      <div class="container">
        <span class="eyebrow">DOCUMENTO LEGAL</span>
        <h1>Termos de Uso</h1>
        <p>Última atualização: Novembro de 2026 · OndeTem Manaus</p>
      </div>
    </section>
    <article class="container narrow legal-page">
      <section class="panel">
        <h2>1. O que é o OndeTem</h2>
        <p>O <strong>OndeTem</strong> é uma plataforma digital que conecta moradores de Manaus (AM) a profissionais autônomos de manutenção e reparos residenciais. O OndeTem atua exclusivamente como canal de descoberta e contato, não sendo empregador, sócio ou intermediário financeiro dos serviços prestados.</p>

        <h2>2. Responsabilidade pelos serviços</h2>
        <p>Orçamentos, prazos, formas de pagamento, garantias e execução do serviço são combinados diretamente entre cliente e profissional (via WhatsApp ou chat interno). Recomendamos sempre solicitar orçamento detalhado antes do início de qualquer trabalho.</p>

        <h2>3. Cadastro e conduta</h2>
        <p>Ao criar uma conta, você declara fornecer informações verdadeiras e manter sua senha em sigilo. É proibido publicar conteúdo ofensivo, fotos de terceiros sem autorização, avaliações falsas ou qualquer tentativa de fraude. Contas que violarem estas regras poderão ser suspensas ou removidas.</p>

        <h2>4. Avaliações e selo Verificado</h2>
        <p>As avaliações refletem a experiência individual de clientes cadastrados. O selo <strong>Verificado</strong> indica que o perfil passou por conferência básica na plataforma, mas não substitui os cuidados normais na contratação.</p>

        <h2>5. Encerramento de conta</h2>
        <p>Você pode solicitar a exclusão definitiva da sua conta e dos seus dados a qualquer momento na página <a class="text-link" href="/conta">Minha conta</a>, conforme nossa <a class="text-link" href="/privacidade">Política de Privacidade (LGPD)</a>.</p>
      </section>
    </article>"""


def privacy_view() -> str:
    return """
    <section class="page-hero">
      <div class="container">
        <span class="eyebrow">LGPD · LEI Nº 13.709/2018</span>
        <h1>Política de Privacidade</h1>
        <p>Transparência sobre como coletamos, protegemos e apagamos seus dados no OndeTem.</p>
      </div>
    </section>
    <article class="container narrow legal-page">
      <section class="panel">
        <h2>1. Dados que coletamos</h2>
        <p>Coletamos apenas o necessário para o funcionamento da plataforma: <strong>nome, e-mail, senha criptografada</strong> e tipo de conta (cliente ou profissional). Para profissionais, exibimos publicamente a categoria, bairro de atuação em Manaus, descrição, portfólio e WhatsApp (quando informado).</p>

        <h2>2. Localização e fotos enviadas</h2>
        <p>A localização do navegador na página de busca é usada apenas naquele momento para calcular a distância aproximada entre bairros e não é armazenada no banco. Toda imagem enviada passa por reprocessamento automático que remove metadados EXIF (incluindo coordenadas GPS da câmera).</p>

        <h2>2.1. Verificação de identidade por CPF (Profissionais)</h2>
        <p>Profissionais que solicitam o selo <strong>Verificado</strong> informam o CPF de forma opcional e mediante consentimento específico. Aplicando o princípio da minimização da LGPD, o sistema valida os dígitos verificadores e armazena <strong>apenas um hash criptográfico irreversível (HMAC-SHA256)</strong> para impedir cadastros duplicados e os dois últimos dígitos mascarados (<code>***.***.***-XX</code>) para conferência administrativa. O número completo do CPF nunca é salvo em texto puro e jamais é exibido publicamente.</p>

        <h2>3. Armazenamento e segurança</h2>
        <p>Senhas são armazenadas com hash criptográfico forte (PBKDF2-HMAC-SHA256 com salt único). Dados cadastrais ficam protegidos em banco PostgreSQL com conexão criptografada (SSL/TLS) e imagens em armazenamento seguro em nuvem (Cloudinary). Utilizamos apenas um cookie estritamente necessário para manter sua sessão ativa (<code>HttpOnly</code> e <code>Secure</code>).</p>

        <h2>4. Seus direitos pela LGPD</h2>
        <p>Nos termos da Lei Geral de Proteção de Dados (Lei nº 13.709/2018), você tem direito de acessar, corrigir e excluir seus dados pessoais. Profissionais podem editar seus dados pelo <a class="text-link" href="/painel">Meu painel</a>, e qualquer usuário pode apagar definitivamente sua conta e histórico em <a class="text-link" href="/conta">Minha conta</a>.</p>
      </section>
    </article>"""


def account_view(user, error: str = "") -> str:
    error_html = f'<p class="form-error" role="alert">{esc(error)}</p>' if error else ""
    role_label = "Profissional" if user["role"] == "profissional" else "Cliente"
    return f"""
    <section class="page-hero">
      <div class="container">
        <span class="eyebrow">PRIVACIDADE E LGPD</span>
        <h1>Minha conta e dados</h1>
        <p>Gerencie sua conta no OndeTem com total controle sobre suas informações.</p>
      </div>
    </section>
    <div class="container narrow legal-page">
      <section class="panel">
        <h2>Resumo da sua conta</h2>
        <div class="contact-line"><span>Nome</span><b>{esc(user['name'])}</b></div>
        <div class="contact-line"><span>Tipo de perfil</span><b>{role_label}</b></div>
        <div class="contact-line"><span>Documentos</span><b><a class="text-link" href="/termos">Termos</a> · <a class="text-link" href="/privacidade">Privacidade</a></b></div>
      </section>

      <section class="panel danger-panel">
        <h2>Excluir minha conta (LGPD)</h2>
        <p>Esta ação apaga permanentemente seu cadastro, perfil profissional, portfólio, avaliações, mensagens e sessões ativas. Não é possível desfazer.</p>
        {error_html}
        <form class="stack-form" method="post" action="/conta/excluir" data-confirm="Tem certeza absoluta? Todos os seus dados serão apagados permanentemente.">
          <input type="hidden" name="csrf" value="{esc(user['csrf'])}">
          <label>Digite sua senha atual para confirmar
            <input type="password" name="password" autocomplete="current-password" required>
          </label>
          <button class="button danger" type="submit">Excluir minha conta permanentemente</button>
        </form>
      </section>
    </div>"""


def admin_view(user, summary: dict, pros: list, recent_reviews: list, top_neighborhoods: list) -> str:
    csrf = esc(user["csrf"])

    pro_rows = "".join(
        f"""<tr>
              <td>
                <div class="admin-pro-cell">
                  {avatar(p['name'], 'tiny', p.get('avatar_url', ''))}
                  <div>
                    <a class="text-link" href="/perfil/{p['user_id']}">{esc(p['name'])}</a>
                    <small>{esc(p['email'])}</small>
                  </div>
                </div>
              </td>
              <td>{esc(p['category'])}</td>
              <td>{esc(p['neighborhood'])}</td>
              <td class="num"><strong>{int(p['whatsapp_clicks'] or 0)}</strong></td>
              <td class="num">{f"{float(p['rating']):.1f} ★ ({int(p['review_count'])})" if p['review_count'] else '—'}</td>
              <td>
                <span class="{'verified-pill' if p['verified'] else ('status busy' if p.get('verification_status') == 'pending' else 'muted')}">
                  {'Verificado' if p['verified'] else ('CPF enviado' if p.get('verification_status') == 'pending' else 'Sem selo')}
                </span>
                {f'<small style="display:block;color:var(--muted);font-size:.72rem;margin-top:3px;">CPF {esc(p["cpf_masked"])}</small>' if p.get('cpf_masked') else ''}
              </td>
              <td>
                <form action="/admin/verificar/{p['user_id']}" method="post">
                  <input type="hidden" name="csrf" value="{csrf}">
                  <button type="submit" class="button small {'secondary' if p['verified'] else ''}">
                    {'Remover selo' if p['verified'] else 'Aprovar selo'}
                  </button>
                </form>
              </td>
            </tr>"""
        for p in pros
    )

    review_rows = "".join(
        f"""<article class="review admin-review">
              <div class="review-top">
                <div>
                  <b>{esc(r['client_name'])}</b> <span class="muted">avaliou</span> <b>{esc(r['pro_name'])}</b>
                  <span class="rating">{'★' * int(r['rating'])}</span>
                  <small class="muted"> · {esc(format_manaus_date(r['created_at']))}</small>
                </div>
                <form action="/admin/avaliacao/remover/{r['id']}" method="post" data-confirm="Remover esta avaliação permanentemente?">
                  <input type="hidden" name="csrf" value="{csrf}">
                  <button type="submit" class="trash-btn" title="Remover avaliação" aria-label="Remover avaliação">{svg_icon('trash', 'ico-xs')}</button>
                </form>
              </div>
              <p>{esc(r['comment'])}</p>
            </article>"""
        for r in recent_reviews
    ) or '<p class="muted">Nenhuma avaliação registrada ainda.</p>'

    neigh_pills = "".join(
        f'<span class="chip">{esc(n["neighborhood"])} · <strong>{int(n["total"])}</strong></span>'
        for n in top_neighborhoods
    )

    return f"""
    <section class="page-hero">
      <div class="container">
        <span class="eyebrow">PAINEL ADMINISTRATIVO · ONDETEM</span>
        <h1>Gestão e Métricas de Manaus</h1>
        <p>Acompanhe cliques reais no WhatsApp, aprove o selo Verificado e modere avaliações.</p>
      </div>
    </section>

    <div class="container kpi-row">
      <div class="kpi-card"><span>Cliques no WhatsApp</span><strong>{summary['wa_clicks']}</strong><small class="muted">{summary['wa_clicks_7d']} nos últimos 7 dias</small></div>
      <div class="kpi-card"><span>Profissionais</span><strong>{summary['pros']}</strong><small class="muted">{summary['verified']} verificados</small></div>
      <div class="kpi-card"><span>Usuários totais</span><strong>{summary['users']}</strong><small class="muted">{summary['conversations']} conversas</small></div>
      <div class="kpi-card"><span>Avaliações</span><strong>{summary['reviews']}</strong><small class="muted">Média {summary['avg_rating']:.1f} ★</small></div>
    </div>

    <div class="container admin-wrap">
      <section class="panel">
        <div class="admin-head">
          <div>
            <h2>Profissionais e Cliques no WhatsApp</h2>
            <p>Ordenados pelos perfis com maior procura em Manaus.</p>
          </div>
          <div class="active-chips">{neigh_pills}</div>
        </div>
        <div class="table-scroll">
          <table class="admin-table">
            <thead>
              <tr>
                <th>Profissional</th>
                <th>Categoria</th>
                <th>Bairro</th>
                <th class="num">Cliques WhatsApp</th>
                <th class="num">Avaliação</th>
                <th>Selo</th>
                <th>Ação</th>
              </tr>
            </thead>
            <tbody>{pro_rows}</tbody>
          </table>
        </div>
      </section>

      <section class="panel">
        <h2>Moderação de avaliações recentes</h2>
        <p>Remova rapidamente comentários ofensivos ou suspeitos de spam.</p>
        {review_rows}
      </section>
    </div>"""
