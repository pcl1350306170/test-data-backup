// Service Worker - 语音速记本离线缓存
var CACHE_NAME = 'voice-notes-v1';
var PAGE_URL = '/';

self.addEventListener('install', function (event) {
  event.waitUntil(
    caches.open(CACHE_NAME).then(function (cache) {
      return cache.addAll([PAGE_URL]);
    }).then(function () {
      return self.skipWaiting();
    })
  );
});

self.addEventListener('activate', function (event) {
  event.waitUntil(
    caches.keys().then(function (keys) {
      return Promise.all(
        keys.filter(function (k) { return k !== CACHE_NAME; })
            .map(function (k) { return caches.delete(k); })
      );
    }).then(function () {
      return self.clients.claim();
    })
  );
});

self.addEventListener('fetch', function (event) {
  var url = new URL(event.request.url);

  // API 请求：透传网络，失败时返回离线 JSON
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(
      fetch(event.request).catch(function () {
        return new Response(
          JSON.stringify({ offline: true, notes: [], categories: [] }),
          { headers: { 'Content-Type': 'application/json' }, status: 503 }
        );
      })
    );
    return;
  }

  // 页面请求：优先缓存，网络更新
  if (event.request.mode === 'navigate' || url.pathname === PAGE_URL) {
    event.respondWith(
      caches.match(PAGE_URL).then(function (cached) {
        var networkFetch = fetch(PAGE_URL).then(function (resp) {
          if (resp.ok) {
            var clone = resp.clone();
            caches.open(CACHE_NAME).then(function (cache) {
              cache.put(PAGE_URL, clone);
            });
          }
          return resp;
        }).catch(function () {
          return cached || new Response('Offline', { status: 503 });
        });
        return cached || networkFetch;
      })
    );
    return;
  }

  // 其他静态资源：缓存优先
  event.respondWith(
    caches.match(event.request).then(function (cached) {
      return cached || fetch(event.request);
    })
  );
});
