// Frontend config.
//
// API_BASE — backend URL. Localhost dev uses local FastAPI; everything
//   else uses the deployed Render instance.
// CF_ANALYTICS_TOKEN — paste your Cloudflare Web Analytics token to
//   enable visitor stats. Leave empty to disable.

const _isDev = location.hostname === 'localhost' || location.hostname === '127.0.0.1';
window.API_BASE = _isDev ? 'http://127.0.0.1:8765' : 'https://cars-api-w7pz.onrender.com';
window.CF_ANALYTICS_TOKEN = '';
