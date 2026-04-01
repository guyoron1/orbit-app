const CACHE_NAME = 'orbit-v3';
const SHELL_ASSETS = ['/', '/manifest.json'];

// ── Install: cache the app shell ──
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(SHELL_ASSETS))
  );
  self.skipWaiting();
});

// ── Activate: clean up old caches ──
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(
        keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k))
      )
    )
  );
  self.clients.claim();
});

// ── Fetch: network-first for API, cache-first for static ──
const API_PATTERNS = ['/api/', '/auth/', '/contacts', '/interactions', '/dashboard', '/nudges', '/quests', '/achievements', '/level', '/parties', '/challenges', '/feed', '/leaderboard', '/location', '/nearby', '/life-events', '/strava/', '/health'];

function isApiRequest(url) {
  const path = new URL(url).pathname;
  return API_PATTERNS.some(p => path.startsWith(p));
}

self.addEventListener('fetch', event => {
  const request = event.request;

  // Network-first for API calls
  if (isApiRequest(request.url)) {
    event.respondWith(
      fetch(request)
        .then(response => response)
        .catch(() => caches.match(request))
    );
    return;
  }

  // Cache-first for static assets
  event.respondWith(
    caches.match(request).then(cached => {
      if (cached) return cached;
      return fetch(request).then(response => {
        if (response.ok) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(request, clone));
        }
        return response;
      });
    })
  );
});

// ── Background Sync: queue failed mutations for retry ──
const DB_NAME = 'orbit-offline-queue';
const STORE_NAME = 'requests';

function openDB() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, 1);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        db.createObjectStore(STORE_NAME, { keyPath: 'id', autoIncrement: true });
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

function enqueueRequest(url, method, headers, body) {
  return openDB().then(db => {
    return new Promise((resolve, reject) => {
      const tx = db.transaction(STORE_NAME, 'readwrite');
      tx.objectStore(STORE_NAME).add({
        url,
        method,
        headers: Object.fromEntries(headers.entries()),
        body,
        timestamp: Date.now(),
      });
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
  });
}

function replayQueue() {
  return openDB().then(db => {
    return new Promise((resolve, reject) => {
      const tx = db.transaction(STORE_NAME, 'readwrite');
      const store = tx.objectStore(STORE_NAME);
      const getAll = store.getAll();

      getAll.onsuccess = () => {
        const requests = getAll.result;
        const replays = requests.map(entry =>
          fetch(entry.url, {
            method: entry.method,
            headers: entry.headers,
            body: entry.body,
          }).then(() => {
            const delTx = db.transaction(STORE_NAME, 'readwrite');
            delTx.objectStore(STORE_NAME).delete(entry.id);
          }).catch(() => {
            // Still offline or failed — leave in queue
          })
        );
        Promise.all(replays).then(resolve).catch(resolve);
      };
      getAll.onerror = () => reject(getAll.error);
    });
  });
}

// Listen for sync events (Background Sync API)
self.addEventListener('sync', event => {
  if (event.tag === 'orbit-offline-sync') {
    event.waitUntil(replayQueue());
  }
});

// Fallback: try replaying on next fetch if sync not supported
self.addEventListener('message', event => {
  if (event.data && event.data.type === 'REPLAY_QUEUE') {
    event.waitUntil(replayQueue());
  }
});
