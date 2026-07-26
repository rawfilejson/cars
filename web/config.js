// Frontend config / backend url + optional Cloudflare analytics token

const _isDev = location.hostname === 'localhost' || location.hostname === '127.0.0.1';
window.API_BASE = _isDev ? 'http://127.0.0.1:8765' : 'https://cars-api-w7pz.onrender.com';
window.CF_ANALYTICS_TOKEN = '';
