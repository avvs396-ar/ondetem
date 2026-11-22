/* OndeTem 2.0 — Interações Progressivas (100% compatível com CSP estrito) */

document.addEventListener('DOMContentLoaded', () => {
  // 1. Menu mobile responsivo
  const navToggle = document.querySelector('[data-nav-toggle]');
  const nav = document.getElementById('main-nav');
  if (navToggle && nav) {
    navToggle.addEventListener('click', () => {
      const open = nav.classList.toggle('open');
      navToggle.setAttribute('aria-expanded', String(open));
    });
  }

  // 2. Campos extras no cadastro quando escolhe "Ofereço serviços"
  const roleInputs = document.querySelectorAll('input[name="role"]');
  const proFields = document.querySelector('.pro-fields');
  if (roleInputs.length && proFields) {
    const syncRole = () => {
      const isPro = document.querySelector('input[name="role"]:checked')?.value === 'profissional';
      proFields.style.display = isPro ? 'grid' : 'none';
      proFields.querySelectorAll('select').forEach((el) => {
        el.required = isPro;
      });
    };
    roleInputs.forEach((input) => input.addEventListener('change', syncRole));
    syncRole();
  }

  // 3. Geolocalização na busca ("Usar minha localização")
  const nearBtn = document.querySelector('[data-near]');
  if (nearBtn) {
    nearBtn.addEventListener('click', () => {
      const status = document.querySelector('[data-location-status]');
      if (!navigator.geolocation) {
        if (status) status.textContent = 'Este navegador não oferece geolocalização.';
        return;
      }
      if (status) status.textContent = 'Obtendo sua localização aproximada...';
      navigator.geolocation.getCurrentPosition(
        (pos) => {
          const url = new URL(location.href);
          url.searchParams.set('lat', pos.coords.latitude.toFixed(5));
          url.searchParams.set('lon', pos.coords.longitude.toFixed(5));
          url.searchParams.set('ordenar', 'proximidade');
          url.searchParams.delete('bairro');
          location.href = url.toString();
        },
        () => {
          if (status) {
            status.textContent = 'Não foi possível acessar sua localização. Selecione seu bairro acima.';
          }
        },
        { timeout: 10000, enableHighAccuracy: false }
      );
    });
  }

  // 4. Favoritos / Salvos persistentes no navegador (localStorage)
  const FAV_KEY = 'ondetem_saved_pros_v1';
  const loadFavs = () => {
    try {
      const parsed = JSON.parse(localStorage.getItem(FAV_KEY) || '[]');
      return new Set(Array.isArray(parsed) ? parsed.map(String) : []);
    } catch {
      return new Set();
    }
  };
  const saveFavs = (set) => {
    try {
      localStorage.setItem(FAV_KEY, JSON.stringify([...set]));
    } catch {
      // Ignora em navegação privada restrita
    }
  };

  const refreshFavUI = () => {
    const favs = loadFavs();
    document.querySelectorAll('[data-fav-id]').forEach((btn) => {
      const id = String(btn.dataset.favId);
      const active = favs.has(id);
      btn.setAttribute('aria-pressed', String(active));
      const labelSpan = btn.querySelector('span');
      if (labelSpan) labelSpan.textContent = active ? 'Salvo' : 'Salvar';
    });

    const badge = document.querySelector('[data-saved-count]');
    if (badge) {
      badge.textContent = String(favs.size);
      badge.hidden = favs.size === 0;
    }

    // Modo /buscar?salvos=1 filtra os cards no cliente
    const savedContainer = document.querySelector('[data-saved-mode="1"]');
    if (savedContainer) {
      const grid = savedContainer.querySelector('[data-results-grid]');
      const counter = savedContainer.querySelector('[data-results-count]');
      if (grid) {
        let visible = 0;
        grid.querySelectorAll('[data-pro-id]').forEach((card) => {
          const keep = favs.has(String(card.dataset.proId));
          card.hidden = !keep;
          if (keep) visible += 1;
        });
        if (counter) {
          counter.textContent = `${visible} ${visible === 1 ? 'profissional salvo' : 'profissionais salvos'}`;
        }
        let emptyEl = grid.querySelector('.saved-empty');
        if (visible === 0 && !emptyEl) {
          emptyEl = document.createElement('div');
          emptyEl.className = 'empty saved-empty';
          emptyEl.innerHTML =
            '<h3>Você ainda não salvou nenhum profissional</h3>' +
            '<p>Toque no ícone de coração nos perfis para comparar depois.</p>' +
            '<a href="/buscar" class="button small">Explorar profissionais</a>';
          grid.appendChild(emptyEl);
        } else if (visible > 0 && emptyEl) {
          emptyEl.remove();
        }
      }
    }
  };

  document.addEventListener('click', (event) => {
    const btn = event.target.closest('[data-fav-id]');
    if (!btn) return;
    const favs = loadFavs();
    const id = String(btn.dataset.favId);
    if (favs.has(id)) favs.delete(id);
    else favs.add(id);
    saveFavs(favs);
    refreshFavUI();
  });
  refreshFavUI();

  // 5. Lightbox de fotos do portfólio (clique ou Enter/Espaço)
  const lightbox = document.getElementById('lightbox');
  const lbImg = document.querySelector('[data-lightbox-img]');
  const lbCap = document.querySelector('[data-lightbox-caption]');
  const closeLightbox = () => {
    if (lightbox) lightbox.hidden = true;
  };
  const openLightbox = (src, text) => {
    if (!lightbox || !lbImg || !lbCap) return;
    lbImg.src = src;
    lbImg.alt = text;
    lbCap.textContent = text;
    lightbox.hidden = false;
  };

  document.querySelectorAll('[data-lightbox-src]').forEach((fig) => {
    fig.addEventListener('click', () => openLightbox(fig.dataset.lightboxSrc, fig.dataset.lightboxText || ''));
    fig.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        openLightbox(fig.dataset.lightboxSrc, fig.dataset.lightboxText || '');
      }
    });
  });

  document.querySelector('[data-lightbox-close]')?.addEventListener('click', closeLightbox);
  lightbox?.addEventListener('click', (e) => {
    if (e.target === lightbox) closeLightbox();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeLightbox();
  });

  // 6. Compartilhar perfil (Web Share API ou copiar link)
  const shareBtn = document.querySelector('[data-share-profile]');
  if (shareBtn) {
    shareBtn.addEventListener('click', async () => {
      const title = shareBtn.dataset.shareTitle || document.title;
      const url = location.href;
      try {
        if (navigator.share) {
          await navigator.share({ title, url });
        } else if (navigator.clipboard) {
          await navigator.clipboard.writeText(url);
          const span = shareBtn.querySelector('span');
          if (span) {
            span.textContent = 'Link copiado!';
            setTimeout(() => { span.textContent = 'Compartilhar'; }, 2200);
          }
        }
      } catch {
        // Usuário cancelou compartilhamento
      }
    });
  }

  // 7. Preenchimento rápido de contas demo na tela de login
  document.querySelectorAll('[data-fill-email]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const email = document.getElementById('login-email');
      const pass = document.getElementById('login-password');
      if (email) email.value = btn.dataset.fillEmail || '';
      if (pass) pass.value = btn.dataset.fillPass || '';
      email?.focus();
    });
  });

  // 8. Chat: rolagem automática, atalho Ctrl+Enter e mensagens rápidas
  const chatBox = document.querySelector('[data-chat-scroll]');
  if (chatBox) chatBox.scrollTop = chatBox.scrollHeight;

  const msgInput = document.getElementById('message');
  if (msgInput) {
    msgInput.addEventListener('keydown', (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
        e.preventDefault();
        msgInput.form?.requestSubmit();
      }
    });
  }

  document.querySelectorAll('[data-quick-msg]').forEach((btn) => {
    btn.addEventListener('click', () => {
      if (!msgInput) return;
      msgInput.value = btn.dataset.quickMsg || '';
      msgInput.focus();
    });
  });

  // 9. Confirmação segura (sem inline JS, respeitando CSP)
  document.addEventListener('submit', (e) => {
    const msg = e.target?.dataset?.confirm;
    if (msg && !window.confirm(msg)) {
      e.preventDefault();
    }
  });

  // 10. Aviso de status desaparece suavemente após 5 segundos
  const notice = document.querySelector('[data-auto-dismiss]');
  if (notice) {
    setTimeout(() => {
      notice.style.opacity = '0';
      setTimeout(() => notice.remove(), 350);
    }, 5000);
  }

  // 11. PWA: registrar Service Worker e exibir banner de instalação
  if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
      navigator.serviceWorker.register('/sw.js').catch(() => {});
    });
  }

  let deferredPrompt = null;
  const pwaBanner = document.getElementById('pwa-banner');
  const pwaInstallBtn = document.getElementById('pwa-install-btn');
  const pwaDismissBtn = document.getElementById('pwa-dismiss-btn');

  window.addEventListener('beforeinstallprompt', (e) => {
    e.preventDefault();
    deferredPrompt = e;
    try {
      if (localStorage.getItem('ondetem_pwa_dismissed') === '1') return;
    } catch {}
    if (pwaBanner) pwaBanner.hidden = false;
  });

  pwaInstallBtn?.addEventListener('click', async () => {
    if (!deferredPrompt) return;
    deferredPrompt.prompt();
    await deferredPrompt.userChoice;
    deferredPrompt = null;
    if (pwaBanner) pwaBanner.hidden = true;
  });

  pwaDismissBtn?.addEventListener('click', () => {
    if (pwaBanner) pwaBanner.hidden = true;
    try { localStorage.setItem('ondetem_pwa_dismissed', '1'); } catch {}
  });
});
