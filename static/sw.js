const CACHE_NAME = 'ondetem-pwa-v3-4';
const STATIC_ASSETS = [
  '/static/style.css',
  '/static/app.js',
  '/static/favicon.svg',
  '/static/icon-192.png',
  '/static/icon-512.png'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(STATIC_ASSETS)).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;

  // Cache-first para arquivos estáticos
  if (url.pathname.startsWith('/static/')) {
    event.respondWith(
      caches.match(req).then((cached) => {
        const net = fetch(req).then((res) => {
          if (res.ok) {
            const copy = res.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(req, copy));
          }
          return res;
        }).catch(() => cached);
        return cached || net;
      })
    );
    return;
  }

  // Network-first para páginas HTML com fallback offline amigável
  if (req.headers.get('accept')?.includes('text/html')) {
    event.respondWith(
      fetch(req).catch(() =>
        new Response(
          '<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Sem conexão · OndeTem</title><style>body{font-family:system-ui,sans-serif;background:#f6fafb;color:#133c55;display:grid;place-items:center;min-height:100vh;margin:0;padding:24px;text-align:center}.card{background:#fff;border:1px solid #dbe6eb;border-radius:18px;padding:32px;max-width:400px}a{display:inline-block;margin-top:16px;background:#f07830;color:#fff;text-decoration:none;font-weight:700;padding:12px 20px;border-radius:10px}</style></head><body><div class="card"><h1>Você está sem internet</h1><p>Reconecte-se ao Wi-Fi ou 4G para buscar profissionais em Manaus.</p><a href="/">Tentar novamente</a></div></body></html>',
          { headers: { 'Content-Type': 'text/html; charset=utf-8' } }
        )
      )
    );
  }
});
