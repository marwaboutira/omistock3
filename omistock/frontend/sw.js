/**
 * OMISTOCK — Service Worker
 * Stratégie hybride : network-first pour CSS/JS locaux, SWR pour le reste.
 *
 * ASSET_VERSION : synchroniser avec ?v= dans les pages HTML.
 * Incrémenter à chaque déploiement CSS/JS/design.
 */
const ASSET_VERSION = '20260628c';
const CACHE_NAME = `omistock-cache-v${ASSET_VERSION}`;

/** @param {string} path */
function versionedUrl(path) {
  const separator = path.includes('?') ? '&' : '?';
  return `${path}${separator}v=${ASSET_VERSION}`;
}

/** Fichiers locaux versionnés + CDN + polices Google */
const PRECACHE_URLS = [
  './app_mobile.html',
  './mobile_scan.html',
  versionedUrl('./style.css'),
  versionedUrl('./erp-sidebar.js'),
  versionedUrl('./manifest.json'),
  './icon-192.png',
  './icon-512.png',
  'https://cdn.tailwindcss.com',
  'https://unpkg.com/html5-qrcode',
  'https://unpkg.com/feather-icons',
  'https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap',
  'https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&display=swap',
];

/**
 * @param {Request} request
 * @returns {boolean}
 */
function shouldUseCacheStrategy(request) {
  if (request.method !== 'GET') return false;
  const url = new URL(request.url);
  if (url.origin === self.location.origin && url.pathname.startsWith('/api')) {
    return false;
  }
  return true;
}

/**
 * CSS/JS/HTML locaux : priorité réseau pour éviter les styles obsolètes.
 * @param {Request} request
 * @returns {boolean}
 */
function isLocalStaticAsset(request) {
  if (request.method !== 'GET') return false;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return false;
  return /\.(css|js|html)$/i.test(url.pathname) || url.pathname === '/' || url.pathname.endsWith('/');
}

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches
      .open(CACHE_NAME)
      .then((cache) =>
        Promise.allSettled(
          PRECACHE_URLS.map((url) =>
            cache.add(new Request(url, { cache: 'reload' }))
          )
        )
      )
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((key) => key !== CACHE_NAME)
            .map((key) => caches.delete(key))
        )
      )
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  if (!shouldUseCacheStrategy(event.request)) return;

  if (isLocalStaticAsset(event.request)) {
    event.respondWith(networkFirst(event.request));
    return;
  }

  event.respondWith(staleWhileRevalidate(event.request));
});

/**
 * Network-first : réseau d'abord, cache uniquement hors ligne.
 * @param {Request} request
 * @returns {Promise<Response>}
 */
async function networkFirst(request) {
  const cache = await caches.open(CACHE_NAME);

  try {
    const networkResponse = await fetch(request);
    if (networkResponse && networkResponse.status === 200) {
      cache.put(request, networkResponse.clone());
    }
    return networkResponse;
  } catch {
    const cachedResponse = await cache.match(request);
    if (cachedResponse) {
      return cachedResponse;
    }

    return new Response('Hors ligne — ressource indisponible.', {
      status: 503,
      statusText: 'Service Unavailable',
      headers: { 'Content-Type': 'text/plain; charset=utf-8' },
    });
  }
}

/**
 * SWR : réponse cache immédiate si disponible, mise à jour réseau en arrière-plan.
 * @param {Request} request
 * @returns {Promise<Response>}
 */
async function staleWhileRevalidate(request) {
  const cache = await caches.open(CACHE_NAME);
  const cachedResponse = await cache.match(request);

  const networkPromise = fetch(request)
    .then((networkResponse) => {
      if (networkResponse && networkResponse.status === 200) {
        cache.put(request, networkResponse.clone());
      }
      return networkResponse;
    })
    .catch(() => undefined);

  if (cachedResponse) {
    networkPromise.catch(() => {});
    return cachedResponse;
  }

  const networkResponse = await networkPromise;
  if (networkResponse) {
    return networkResponse;
  }

  return (
    (await cache.match('./app_mobile.html')) ||
    new Response('Hors ligne — ressource indisponible.', {
      status: 503,
      statusText: 'Service Unavailable',
      headers: { 'Content-Type': 'text/plain; charset=utf-8' },
    })
  );
}
