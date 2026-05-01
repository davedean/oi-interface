const CACHE = 'oi-android-pwa-v1';
const SHELL = [
  './', './index.html', './manifest.webmanifest', './src/styles.css', './src/main.js',
  './src/audio/cache.js', './src/audio/playback.js', './src/audio/pcm16.js', './src/audio/recorder.js',
  './src/datp/client.js', './src/datp/envelope.js',
  './src/state/map-command.js', './src/state/model.js',
  './src/ui/controller.js', './src/ui/render.js',
];
self.addEventListener('install', (event) => event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(SHELL))));
self.addEventListener('activate', (event) => event.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key))))));
self.addEventListener('fetch', (event) => {
  if (event.request.method !== 'GET') return;
  event.respondWith(caches.match(event.request).then((cached) => cached || fetch(event.request)));
});
