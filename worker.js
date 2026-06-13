// Cloudflare Worker — სტატიკურ frontend-ს ემსახურება + Render backend-ს ცოცხალს უნახავს.
// fetch() assets-ს აბრუნებს security header-ებით; scheduled() ყოველ 10წთ /healthz-ს
// ეხება, რომ Render free-tier არ დაიძინოს.

const API_HEALTH = "https://cars-api-w7pz.onrender.com/healthz";

const CSP = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.tailwindcss.com https://static.cloudflareinsights.com",
  "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
  "font-src 'self' https://fonts.gstatic.com",
  "img-src 'self' data: https:",
  "connect-src 'self' https://cars-api-w7pz.onrender.com https://cloudflareinsights.com https://static.cloudflareinsights.com",
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
    // resp.body-ის ხელახლა შეფუთვა Content-Encoding-ს ურევდა (SPA fallback-ზე
    // body ცარიელი მოდიოდა). new Response(body, resp) აკლონებს უცვლელად.
    const out = new Response(resp.body, resp);
    for (const [key, value] of Object.entries(SECURITY_HEADERS)) {
      out.headers.set(key, value);
    }
    return out;
  },

  async scheduled(event, env, ctx) {
    ctx.waitUntil(fetch(API_HEALTH).catch(() => {}));
  },
};
