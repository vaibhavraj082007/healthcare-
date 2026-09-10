/**
 * RetinaShield — Service Worker (Asset Cache ONLY)
 *
 * SCOPE AND SECURITY POLICY:
 *   This service worker caches ONLY static application assets:
 *     - JavaScript bundles
 *     - CSS stylesheets
 *     - Static fonts and icons
 *     - Next.js build manifests
 *
 *   The following are EXPLICITLY EXCLUDED and are NEVER intercepted, cached,
 *   or inspected by this service worker:
 *     - /api/*          — all backend API calls
 *     - /login          — authentication flows
 *     - Any URL containing a query string with patient identifiers
 *     - File uploads (multipart/form-data)
 *     - Image blob URLs
 *
 *   PATIENT DATA: No patient records, images, clinician reviews, or session
 *   credentials are ever stored in the Cache API or any browser storage by
 *   this service worker. Medical data is held exclusively in the encrypted
 *   facility database on the local server — not in the browser.
 *
 *   OFFLINE INFERENCE: This service worker does NOT provide offline MATLAB
 *   inference. A cached web page without the facility daemon running cannot
 *   perform fundus image analysis. The UI will display a clear offline banner
 *   and disable inference-dependent actions when the daemon is unreachable.
 *
 * Version: 1.0.0
 */

const CACHE_VERSION = 'rs-assets-v1';

// Static assets eligible for caching (cache-first strategy)
const CACHEABLE_EXTENSIONS = new Set([
  '.js', '.css', '.woff', '.woff2', '.ttf', '.otf',
  '.png', '.ico', '.svg', '.webp',
]);

// URL patterns that must NEVER be cached
const BLOCKED_PATTERNS = [
  /^\/api\//,
  /^\/login/,
  /^\/auth/,
  /\.php$/,
  /[?&](patient|encounter|image|token|auth)/i,
];

const NEXT_STATIC = '/_next/static/';
const NEXT_IMAGE  = '/_next/image';  // Never cache — dynamically generated

// ── Install ───────────────────────────────────────────────────────────────────

self.addEventListener('install', (event) => {
  // Skip waiting so updated SW activates immediately
  event.waitUntil(self.skipWaiting());
  console.info('[SW] Installed — asset-only cache mode.');
});

// ── Activate ──────────────────────────────────────────────────────────────────

self.addEventListener('activate', (event) => {
  event.waitUntil(
    (async () => {
      // Remove caches from previous SW versions
      const keys = await caches.keys();
      await Promise.all(
        keys
          .filter((key) => key !== CACHE_VERSION)
          .map((key) => {
            console.info(`[SW] Removing old cache: ${key}`);
            return caches.delete(key);
          })
      );
      // Take control of all open clients immediately
      await self.clients.claim();
      console.info('[SW] Activated. Old caches cleared.');
    })()
  );
});

// ── Fetch interception ────────────────────────────────────────────────────────

self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);

  // ── Rule 1: Only intercept GET requests ───────────────────────────────────
  if (request.method !== 'GET') {
    return; // Let POST/PATCH/PUT/DELETE pass through unmodified
  }

  // ── Rule 2: Only intercept same-origin requests ───────────────────────────
  if (url.origin !== self.location.origin) {
    return;
  }

  // ── Rule 3: Enforce blocked-pattern list (API, auth, patient data) ─────────
  for (const pattern of BLOCKED_PATTERNS) {
    if (pattern.test(url.pathname + url.search)) {
      return; // Network-only: do NOT cache, do NOT intercept
    }
  }

  // ── Rule 4: Never cache _next/image (dynamic image resizing) ──────────────
  if (url.pathname.startsWith(NEXT_IMAGE)) {
    return;
  }

  // ── Rule 5: Cache Next.js static assets (cache-first) ────────────────────
  if (url.pathname.startsWith(NEXT_STATIC)) {
    event.respondWith(cacheFirst(request));
    return;
  }

  // ── Rule 6: Cache other static file types (cache-first) ──────────────────
  const ext = '.' + (url.pathname.split('.').pop() || '');
  if (CACHEABLE_EXTENSIONS.has(ext)) {
    event.respondWith(cacheFirst(request));
    return;
  }

  // ── Rule 7: Navigation requests (HTML pages) — network with offline fallback
  if (request.mode === 'navigate') {
    event.respondWith(networkWithOfflineFallback(request));
    return;
  }

  // All other requests: pass through to network
});

// ── Cache strategies ──────────────────────────────────────────────────────────

/**
 * Cache-first: return cached response if fresh, otherwise fetch and cache.
 * Used for versioned static assets that rarely change.
 */
async function cacheFirst(request) {
  const cache = await caches.open(CACHE_VERSION);
  const cached = await cache.match(request);
  if (cached) {
    return cached;
  }
  try {
    const response = await fetch(request);
    if (response.ok) {
      cache.put(request, response.clone());
    }
    return response;
  } catch {
    return new Response('Asset unavailable offline.', { status: 503 });
  }
}

/**
 * Network-first for HTML pages, with a minimal offline fallback.
 * The fallback is a plain text notice — NO patient data, NO cached page content.
 */
async function networkWithOfflineFallback(request) {
  try {
    return await fetch(request);
  } catch {
    return new Response(
      [
        '<!DOCTYPE html>',
        '<html lang="en"><head>',
        '<meta charset="UTF-8">',
        '<title>RetinaShield — Offline</title>',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        '</head><body style="font-family:system-ui;max-width:600px;margin:4rem auto;padding:0 1rem">',
        '<h1>RetinaShield Facility Node</h1>',
        '<p><strong>Application server not reachable.</strong></p>',
        '<p>The facility service may be starting up or temporarily unavailable.</p>',
        '<ul>',
        '<li>Verify the facility service daemon is running.</li>',
        '<li>Check the local network connection to the facility computer.</li>',
        '<li>Images captured while offline are preserved in the encrypted local queue.</li>',
        '<li>MATLAB inference requires the facility daemon — it does NOT run in the browser.</li>',
        '</ul>',
        '<p style="color:#6b7280;font-size:0.85rem">',
        'RetinaShield — Research Screening Tool. Not approved for autonomous clinical diagnosis.',
        '</p>',
        '</body></html>',
      ].join('\n'),
      {
        status: 200,
        headers: { 'Content-Type': 'text/html; charset=utf-8' },
      }
    );
  }
}
