/**
 * OMISTOCK — Service Worker (kill switch)
 * Se désinstalle immédiatement et supprime tous les caches.
 * Les pages ERP n'ont pas besoin d'offline cache.
 */

self.addEventListener('install', () => self.skipWaiting());

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.map((key) => caches.delete(key))))
      .then(() => self.registration.unregister())
      .then(() => self.clients.matchAll({ includeUncontrolled: true, type: 'window' }))
      .then((clients) => clients.forEach((client) => {
        if (client.url && 'navigate' in client) client.navigate(client.url);
      }))
  );
});
