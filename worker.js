// Cloudflare Worker: serves the static frontend and keeps the Render backend awake.
// fetch() returns the assets with security headers; scheduled() pings /healthz every
// 10 minutes so the Render free tier does not fall asleep.

const API_HEALTH = "https://cars-api-w7pz.onrender.com/healthz";

const CSP = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.tailwindcss.com https://static.cloudflareinsights.com",
  "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
  "font-src 'self' https://fonts.gstatic.com",
  "img-src 'self' data: https:",
  "connect-src 'self' https://cars-api-w7pz.onrender.com https://cloudflareinsights.com https://static.cloudflareinsights.com https://translate.googleapis.com",
  "frame-src https://www.youtube.com https://www.youtube-nocookie.com",
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "object-src 'none'",
].join("; ");

const SECURITY_HEADERS = {
  "Content-Security-Policy": CSP,
  "X-Frame-Options": "DENY",
  "X-Content-Type-Options": "nosniff",
  "Referrer-Policy": "strict-origin-when-cross-origin",
  "Permissions-Policy": "geolocation=(), microphone=(), camera=(), payment=()",
  "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
  "Cross-Origin-Opener-Policy": "same-origin",
};

export default {
  async fetch(request, env) {
    const resp = await env.ASSETS.fetch(request);
    const headers = new Headers(resp.headers);
    // env.ASSETS hands back a decoded body, but the Content-Encoding and
    // Content-Length headers still describe the encoded one. The browser then fails
    // to decode it and the body comes out empty, especially with Cloudflare's newer
    // zstd. Drop those headers so CF compresses the response again itself.
    headers.delete("content-encoding");
    headers.delete("content-length");
    for (const [key, value] of Object.entries(SECURITY_HEADERS)) {
      headers.set(key, value);
    }
    return new Response(resp.body, {
      status: resp.status,
      statusText: resp.statusText,
      headers,
    });
  },

  async scheduled(event, env, ctx) {
    ctx.waitUntil(fetch(API_HEALTH).catch(() => {}));
  },
};
