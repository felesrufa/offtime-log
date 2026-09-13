/*
 * オフライン用 Service Worker。
 * アプリ本体(HTML/JS/manifest/アイコン)をキャッシュするだけ。データ(log.txt)は扱わない。
 * ファイルを更新したら CACHE_VERSION を上げる（古いキャッシュは activate で消える）。
 */
const CACHE_VERSION = "retainer-log-v1";
const SHELL = [
  "./",
  "./index.html",
  "./aggregate.js",
  "./manifest.webmanifest",
  "./icon-180.png",
  "./icon-192.png",
  "./icon-512.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_VERSION).then((cache) => cache.addAll(SHELL)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE_VERSION).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

// ネットワーク優先・失敗したらキャッシュ（更新を取りこぼさず、オフラインでも開ける）
self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET") return;
  const url = new URL(event.request.url);
  if (url.origin !== location.origin) return;
  event.respondWith(
    fetch(event.request)
      .then((res) => {
        const copy = res.clone();
        caches.open(CACHE_VERSION).then((cache) => cache.put(event.request, copy)).catch(() => {});
        return res;
      })
      .catch(() => caches.match(event.request, { ignoreSearch: true }).then((hit) => hit || caches.match("./index.html")))
  );
});
