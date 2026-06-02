// Cloudflare Worker — სტატიკურ frontend-ს ემსახურება + Render backend-ს ცოცხალს უნახავს.
// scheduled() ყოველ 10 წუთში ეხება /healthz-ს, რომ free-tier Render არ "დაიძინოს"
// (15 წთ უმოქმედობის შემდეგ იძინებს → პირველი ვიზიტი ~30წმ cold start). fetch()
// უბრალოდ assets-ს აბრუნებს (SPA routing-ით).

const API_HEALTH = "https://cars-api-w7pz.onrender.com/healthz";

export default {
  async fetch(request, env) {
    return env.ASSETS.fetch(request);
  },

  async scheduled(event, env, ctx) {
    ctx.waitUntil(fetch(API_HEALTH).catch(() => {}));
  },
};
