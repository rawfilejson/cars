// Frontend logic for index.html. Plain browser JavaScript, no framework
// and no build step - config.js and i18n.js load before this file.

const API_BASE = window.API_BASE || 'http://127.0.0.1:8765';

const CLIENT_ID = (() => {
    try {
        let id = localStorage.getItem('cdb_cid');
        if (!id || !/^[A-Za-z0-9_-]{8,64}$/.test(id)) {
            const raw = (crypto.randomUUID && crypto.randomUUID()) ||
                (Date.now().toString(36) + Math.random().toString(36).slice(2));
            id = raw.replace(/[^A-Za-z0-9_-]/g, '').slice(0, 64);
            localStorage.setItem('cdb_cid', id);
        }
        return id;
    } catch (_) {
        return '';
    }
})();

let lastResponse = null;
let currentPage = 1;
const _searchCache = new Map();
const _SEARCH_TTL = 300000;

async function loadStats() {
    try {
        const resp = await fetch(`${API_BASE}/stats`);
        if (!resp.ok) return;
        const data = await resp.json();
        _totalCars = data.total_cars;
        updateSearchBtnCount();
    } catch (_) {}
}

let _totalCars = 0;
let _lastCount = null;

function updateSearchBtnCount() {
    const n = _lastCount != null ? _lastCount : _totalCars;
    const label = t('btn_search') + (n ? ` (${Number(n).toLocaleString()})` : '');
    document.querySelectorAll('[data-search-btn]').forEach(b => {
        b.textContent = label;
    });
}

let _countTimer = null,
    _countSeq = 0;

function scheduleLiveCount() {
    clearTimeout(_countTimer);
    _countTimer = setTimeout(fetchLiveCount, 400);
}
async function fetchLiveCount() {
    const payload = buildSearchPayload();
    delete payload.page;
    delete payload.sort;
    const seq = ++_countSeq; // ignore a slow response that a newer request already superseded
    try {
        const resp = await fetch(`${API_BASE}/search/count`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(payload),
        });
        if (!resp.ok || seq !== _countSeq) return;
        _lastCount = (await resp.json()).total_count;
        updateSearchBtnCount();
    } catch (_) {}
}

window.toggleLangMenu = function(e) {
    if (e) e.stopPropagation();
    const pop = document.querySelector('#lang-menu .lang-pop');
    const trig = document.querySelector('#lang-menu .lang-trigger');
    if (!pop) return;
    const willOpen = pop.hasAttribute('hidden');
    pop.toggleAttribute('hidden');
    if (trig) trig.setAttribute('aria-expanded', willOpen ? 'true' : 'false');
    if (willOpen) {
        const active = pop.querySelector('.lang-opt.is-active') || pop.querySelector('.lang-opt');
        if (active) active.focus();
    }
};

function _closeLangMenu(focusTrigger) {
    const pop = document.querySelector('#lang-menu .lang-pop');
    const trig = document.querySelector('#lang-menu .lang-trigger');
    if (pop && !pop.hidden) pop.setAttribute('hidden', '');
    if (trig) {
        trig.setAttribute('aria-expanded', 'false');
        if (focusTrigger) trig.focus();
    }
}
window.pickLang = function(lang) {
    setLang(lang);
    _closeLangMenu(true);
};
document.addEventListener('click', (e) => {
    const pop = document.querySelector('#lang-menu .lang-pop');
    if (pop && !pop.hidden && !e.target.closest('#lang-menu')) _closeLangMenu(false);
});
document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape') return;
    const pop = document.querySelector('#lang-menu .lang-pop');
    if (pop && !pop.hidden) _closeLangMenu(true);
});

document.addEventListener('langchange', () => {
    loadStats();
    updateSearchBtnCount();
    refillFacets();
    refreshDropdowns();
    renderRecent();
    if (window._refreshCompareUI) _refreshCompareUI();
    if (parseRoute().view === 'detail' && _detailCar) {
        renderDetail(_detailCar);
        return;
    }
    if (lastResponse) renderResults(lastResponse);
});

const _FILTER_FIELDS = {
    'year-from': 'year_from',
    'year-to': 'year_to',
    'price-from': 'price_from',
    'price-to': 'price_to',
    'mileage-from': 'mileage_from',
    'mileage-to': 'mileage_to',
};

function buildSearchPayload() {
    const payload = {
        page: currentPage
    };
    const q = document.getElementById('search-input').value.trim();
    if (q) payload.query = q;

    for (const [id, key] of Object.entries(_FILTER_FIELDS)) {
        const raw = document.getElementById('f-' + id).value;
        const n = parseInt(raw, 10);
        if (!Number.isNaN(n) && n >= 0) payload[key] = n;
    }

    const MULTI = {
        'f-brand': 'manufacturers',
        'f-model': 'models',
        'f-body': 'body_types',
        'f-fuel': 'fuels',
        'f-gearbox': 'gearboxes',
        'f-drive': 'drives',
        'f-location': 'locations',
    };
    for (const [id, key] of Object.entries(MULTI)) {
        const sel = document.getElementById(id);
        if (!sel) continue;
        const selOpts = Array.from(sel.selectedOptions).filter(o => o.value);
        const total = Array.from(sel.options).filter(o => o.value && !o.disabled).length;
        // none OR all selected both mean "no constraint" - skip the redundant, oversized list
        if (total && selOpts.length >= total) continue;
        const vals = selOpts.flatMap(o => o.value.split(_LOC_SEP)).filter(Boolean);
        if (vals.length) payload[key] = vals;
    }

    const customs = document.getElementById('f-customs').value;
    if (customs) payload.customs_cleared = (customs === 'yes');

    const sort = document.getElementById('f-sort').value;
    if (sort) payload.sort = sort;

    return payload;
}

(function populateYears() {
    const now = new Date().getFullYear();
    const yFrom = document.getElementById('f-year-from');
    const yTo = document.getElementById('f-year-to');
    const opts = ['<option value=""></option>'];
    for (let y = now; y >= 1900; y--) {
        opts.push(`<option value="${y}">${y}</option>`);
    }
    const html = opts.join('');
    yFrom.innerHTML = html;
    yTo.innerHTML = html;
    const fixRange = (changed) => {
        const f = parseInt(yFrom.value, 10),
            t = parseInt(yTo.value, 10);
        if (f && t && f > t)(changed === 'from' ? yTo : yFrom).value = (changed === 'from' ? yFrom : yTo).value;
    };
    yFrom.addEventListener('change', () => fixRange('from'));
    yTo.addEventListener('change', () => fixRange('to'));
})();

(function wireNumRanges() {
    const swap = (from, to) => {
        const f = parseFloat(from.value),
            t = parseFloat(to.value);
        if (!Number.isNaN(f) && !Number.isNaN(t) && f > t) {
            const tmp = from.value;
            from.value = to.value;
            to.value = tmp;
        }
    };
    for (const [a, b] of [
            ['f-price-from', 'f-price-to'],
            ['f-mileage-from', 'f-mileage-to']
        ]) {
        const from = document.getElementById(a),
            to = document.getElementById(b);
        from.addEventListener('change', () => swap(from, to));
        to.addEventListener('change', () => swap(from, to));
    }
})();

const MILEAGE_MAX = 1000000;

function _fmtKm(n) {
    return n >= MILEAGE_MAX ? '1,000,000+' : Number(n).toLocaleString();
}

function initMileageSlider() {
    const from = document.getElementById('mileage-r-from');
    const to = document.getElementById('mileage-r-to');
    const fill = document.getElementById('mileage-fill');
    const vFrom = document.getElementById('mileage-v-from');
    const vTo = document.getElementById('mileage-v-to');
    const hFrom = document.getElementById('f-mileage-from');
    const hTo = document.getElementById('f-mileage-to');
    if (!from || !to) return;
    const apply = (which) => {
        let a = +from.value,
            b = +to.value;
        if (a > b) {
            if (which === 'from') {
                a = b;
                from.value = a;
            } else {
                b = a;
                to.value = b;
            }
        }
        fill.style.left = (a / MILEAGE_MAX * 100) + '%';
        fill.style.width = ((b - a) / MILEAGE_MAX * 100) + '%';
        vFrom.textContent = _fmtKm(a);
        vTo.textContent = _fmtKm(b);
        hFrom.value = a > 0 ? a : '';
        hTo.value = b < MILEAGE_MAX ? b : '';
        updateFilterResets();
    };
    from.addEventListener('input', () => apply('from'));
    to.addEventListener('input', () => apply('to'));
    window._resetMileage = () => {
        from.value = 0;
        to.value = MILEAGE_MAX;
        apply('init');
    };
    apply('init');
}

window.toggleMoreFilters = function() {
    const m = document.getElementById('more-filters');
    const btn = document.querySelector('.more-toggle');
    if (!m || !btn) return;
    const opening = m.hasAttribute('hidden');
    m.toggleAttribute('hidden', !opening);
    btn.classList.toggle('open', opening);
    const lbl = btn.querySelector('span');
    if (lbl) lbl.textContent = t(opening ? 'less_filters' : 'more_filters');
    if (opening) refreshDropdowns();
};

window.clearFilters = function() {
    for (const id of Object.keys(_FILTER_FIELDS)) document.getElementById('f-' + id).value = '';
    if (window._resetMileage) window._resetMileage();
    document.getElementById('f-sort').value = '';
    document.getElementById('f-customs').value = '';
    // back to the default state: every multi-select all checked (== no filter)
    for (const id of ['f-brand', 'f-body', 'f-fuel', 'f-gearbox', 'f-drive', 'f-location']) {
        const sel = document.getElementById(id);
        if (sel) Array.from(sel.options).forEach(o => o.selected = !!o.value);
    }
    onBrandChange(); // empties + disables the model dropdown while brands are all-selected
    updateFilterResets();
    refreshDropdowns();
};

const _RESET_GROUPS = {
    brand: ['f-brand'],
    model: ['f-model'],
    year: ['f-year-from', 'f-year-to'],
    price: ['f-price-from', 'f-price-to'],
    mileage: ['f-mileage-from', 'f-mileage-to'],
    body_type: ['f-body'],
    fuel: ['f-fuel'],
    gearbox: ['f-gearbox'],
    drive: ['f-drive'],
    location: ['f-location'],
    customs: ['f-customs'],
};

const _scrollLocks = new Set();

function lockScroll(key) {
    _scrollLocks.add(key);
    document.body.style.overflow = 'hidden';
}

function unlockScroll(key) {
    _scrollLocks.delete(key);
    if (!_scrollLocks.size) document.body.style.overflow = '';
}

window.toggleSidebar = function() {
    const sb = document.getElementById('filter-sidebar');
    if (!sb) return;
    const open = sb.classList.toggle('open');
    if (window.matchMedia('(max-width: 860px)').matches) {
        open ? lockScroll('sheet') : unlockScroll('sheet');
    } else if (!open) unlockScroll('sheet');
};
window.applyFilters = function() {
    const sb = document.getElementById('filter-sidebar');
    if (sb) sb.classList.remove('open');
    unlockScroll('sheet');
    doSearch();
};

window.resetFilter = function(kind) {
    (_RESET_GROUPS[kind] || []).forEach((id) => {
        const el = document.getElementById(id);
        if (!el) return;
        // the default state of a multi-select is all checked (== no filter)
        if (el.multiple) Array.from(el.options).forEach(o => o.selected = !!o.value);
        else el.value = '';
    });
    if (kind === 'brand') onBrandChange();
    if (kind === 'mileage' && window._resetMileage) window._resetMileage();
    updateFilterResets();
    refreshDropdowns();
};

function updateFilterResets() {
    for (const [kind, ids] of Object.entries(_RESET_GROUPS)) {
        const group = document.querySelector(`[data-filter="${kind}"]`);
        if (!group) continue;
        const hasVal = ids.some((id) => {
            const el = document.getElementById(id);
            if (!el) return false;
            if (el.multiple) {
                // a subset narrows. none or all selected both mean "all", so no filter
                const sel = Array.from(el.selectedOptions).filter(o => o.value).length;
                const total = Array.from(el.options).filter(o => o.value).length;
                return sel > 0 && sel < total;
            }
            return !!el.value;
        });
        group.classList.toggle('has-val', hasVal);
    }
}

let _makes = {};

async function loadMakes() {
    try {
        const resp = await fetch(`${API_BASE}/makes`);
        if (!resp.ok) return;
        _makes = (await resp.json()).makes || {};
    } catch {
        return;
    }
    const all = Object.keys(_makes);
    const POP_N = 12;
    const popular = all.slice(0, POP_N);
    const rest = all.slice(POP_N).sort((a, b) => a.localeCompare(b));
    const opt = (n) => `<option value="${escapeHtml(n)}">${escapeHtml(n)}</option>`;
    let html = popular.map(opt).join('');
    if (rest.length) html += '<option disabled></option>'; // separator line
    html += rest.map(opt).join('');
    const brand = document.getElementById('f-brand');
    // rebuild, carrying any existing pick across - a second call must not wipe it
    const placeholder = brand.querySelector('option[value=""]');
    const keep = new Set(Array.from(brand.selectedOptions).map(o => o.value).filter(Boolean));
    brand.innerHTML = '';
    if (placeholder) brand.appendChild(placeholder);
    brand.insertAdjacentHTML('beforeend', html);
    // all brands checked by default (== no brand filter), on the first fill only
    const firstFill = !brand.dataset.filled && !keep.size;
    Array.from(brand.options).forEach(o => {
        o.selected = !!o.value && (firstFill || keep.has(o.value));
    });
    brand.dataset.filled = '1';
    if (brand._cdd) brand._cdd.render();
    onBrandChange(); // keeps the model dropdown in sync with the brand state
}

const _BRAND_COLORS = {
    'BMW': '#0066B1',
    'Mercedes-Benz': '#2B2B2B',
    'Toyota': '#D81E2C',
    'Audi': '#A50E26',
    'Volkswagen': '#00237A',
    'Honda': '#C4122F',
    'Ford': '#1B3F8B',
    'Hyundai': '#002C5F',
    'Nissan': '#B3002A',
    'Lexus': '#2A2A2A',
    'Kia': '#0B141B',
    'Mazda': '#1A1A1A',
    'Porsche': '#8E2420',
    'Chevrolet': '#A37B2C',
    'Mitsubishi': '#C40010',
    'Subaru': '#013C74',
    'Volvo': '#003057',
    'Land Rover': '#00592C',
    'Jeep': '#16321F',
    'Tesla': '#B00000',
    'Opel': '#2B2B2B',
    'Renault': '#1A2E4A',
    'Peugeot': '#15244A',
    'Fiat': '#7A1626',
    'Suzuki': '#C4051A',
    'Skoda': '#0E3A2F',
    'Mini': '#1A1A1A',
    'Jaguar': '#14361F',
    'Bentley': '#14342A',
    'Maserati': '#14233F',
    'Cadillac': '#7E1A2A',
    'Acura': '#2A2A2A',
    'Infiniti': '#2A2A2A',
    'Genesis': '#2A2A2A',
    'Dodge': '#8E1520',
    'GMC': '#8E1520',
    'Chrysler': '#14233F',
};

function _brandColor(name) {
    if (_BRAND_COLORS[name]) return _BRAND_COLORS[name];
    let h = 0;
    for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) >>> 0;
    return `hsl(${h % 360} 52% 36%)`;
}

function _brandInitials(name) {
    const parts = name.split(/[\s\-]+/).filter(Boolean);
    if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
    return name.slice(0, 2).toUpperCase();
}

function _brandLogoSlug(name) {
    return name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
}

function _brandBadge(name) {
    return `<span class="brand-badge brand-badge-logo"><img class="brand-logo" src="logos/${_brandLogoSlug(name)}.png" alt="" loading="lazy" data-brand="${escapeHtml(name)}" onerror="_logoFail(this)"></span>`;
}
window._logoFail = function(img) {
    const span = img.parentElement;
    if (!span) return;
    span.classList.remove('brand-badge-logo');
    span.style.background = _brandColor(img.getAttribute('data-brand') || '');
    span.textContent = _brandInitials(img.getAttribute('data-brand') || '');
};

// graceful car-silhouette shown wherever a photo is missing or fails to load
const CAR_GLYPH = '<svg class="ph-car" viewBox="0 0 48 28" aria-hidden="true"><path d="M4 19l3 0 3-7c.5-1 1.5-1.6 2.6-1.6h15c1 0 2 .5 2.7 1.3l4.3 5.5 7 1c1 .2 2 1 2 2v1.3H4z" fill="currentColor" opacity=".5"/><circle cx="14.5" cy="21.4" r="3.4" fill="currentColor"/><circle cx="34" cy="21.4" r="3.4" fill="currentColor"/><circle cx="14.5" cy="21.4" r="1.3" fill="#fff"/><circle cx="34" cy="21.4" r="1.3" fill="#fff"/></svg>';
// render an image cell, or the placeholder straight away when there is no thumb
function _cmpImg(thumb, cls) {
    return thumb ?
        `<img class="${cls}" src="${escapeHtml(thumb)}" alt="" loading="lazy" onerror="_photoFail(this)">` :
        `<span class="${cls} car-ph">${CAR_GLYPH}</span>`;
}
window._photoFail = function(img) {
    const span = document.createElement('span');
    span.className = img.className + ' car-ph';
    span.innerHTML = CAR_GLYPH;
    img.replaceWith(span);
};

let _facets = {};

async function loadFacets() {
    try {
        const resp = await fetch(`${API_BASE}/facets`);
        if (!resp.ok) return;
        _facets = (await resp.json()).facets || {};
    } catch {
        return;
    }
    refillFacets();
}

function fillFacet(id, values, anyKey) {
    const sel = document.getElementById(id);
    if (!sel || !values) return;
    const keep = new Set(Array.from(sel.selectedOptions).map(o => o.value));
    const firstFill = !sel.dataset.filled; // all checked by default on the initial fill only
    sel.innerHTML = `<option value="">${t(anyKey || 'any_opt')}</option>` +
        values.map(v => `<option value="${escapeHtml(v)}"${(firstFill || keep.has(v)) ? ' selected' : ''}>${escapeHtml(tval(v))}</option>`).join('');
    sel.dataset.filled = '1';
    if (sel._cdd) sel._cdd.render();
}

function refillFacets() {
    fillFacet('f-body', _facets.body_type);
    fillFacet('f-fuel', _facets.fuel);
    fillFacet('f-gearbox', _facets.gearbox);
    fillFacet('f-drive', _facets.drive);
    fillLocationFacet(_facets.location);
}

const _LOC_SEP = '\u001F';
const _LOC_COUNTRY_SHORT = {
    'არაბეთის გაერთიანებული საემიროები': 'ემირატები'
};

function locLabel(raw) {
    const s = String(raw || '').replace(/\s*\(AUTOPAPA\)/gi, '').trim();
    if (!s) return '';
    if (/გზაში/.test(s)) return t('loc_transit');
    const parts = s.split(',').map(p => p.trim()).filter(Boolean);
    if (parts.length > 1 && parts[parts.length - 1] === 'საქართველო') parts.pop();
    return parts.map(p => tval(_LOC_COUNTRY_SHORT[p] || p)).join(', ');
}

function fillLocationFacet(values) {
    const sel = document.getElementById('f-location');
    if (!sel || !values) return;
    const keep = new Set(Array.from(sel.selectedOptions).flatMap(o => o.value.split(_LOC_SEP)));
    const firstFill = !sel.dataset.filled; // all checked by default on the initial fill only
    const groups = new Map();
    for (const v of values) {
        const label = locLabel(v);
        if (!label) continue;
        if (!groups.has(label)) groups.set(label, []);
        groups.get(label).push(v);
    }
    sel.innerHTML = `<option value="">${t('location_any')}</option>` +
        Array.from(groups, ([label, raws]) =>
            `<option value="${escapeHtml(raws.join(_LOC_SEP))}"${(firstFill || raws.some(r => keep.has(r))) ? ' selected' : ''}>${escapeHtml(label)}</option>`
        ).join('');
    sel.dataset.filled = '1';
    if (sel._cdd) sel._cdd.render();
}

function _seriesOf(brand, model) {
    const b = brand.toLowerCase();
    const m = model.trim();
    if (b === 'bmw') {
        if (/^\d/.test(m)) return m[0] + 'er';
        if (/^x\d?/i.test(m)) return 'X';
        if (/^m\d?/i.test(m)) return 'M';
        if (/^i\d?/i.test(m)) return 'i';
        if (/^z\d?/i.test(m)) return 'Z';
    } else if (b === 'mercedes-benz' || b === 'mercedes') {
        const c = m.toUpperCase().match(/^(GLE|GLC|GLS|GLA|GLB|GLK|GL|CLA|CLS|CLK|SLK|SLC|SL|[ABCEGRSVX])\b/);
        if (c) return c[1] + '-Class';
    } else if (b === 'audi') {
        const c = m.match(/^(RS|S|A|Q|TT|R8)/i);
        if (c) return c[1].toUpperCase();
    }
    return null;
}

function _buildModelOptions(brands, keep) {
    const out = [`<option value="">${escapeHtml(t('model_any'))}</option>`];
    const multiBrand = brands.length > 1;
    const opt = (m) => `<option value="${escapeHtml(m)}"${keep.has(m) ? ' selected' : ''}>${escapeHtml(m)}</option>`;
    for (const b of brands) {
        const groups = new Map();
        const flat = [];
        for (const m of (_makes[b] || [])) {
            const s = _seriesOf(b, m);
            if (s) {
                if (!groups.has(s)) groups.set(s, []);
                groups.get(s).push(m);
            } else flat.push(m);
        }
        for (const [series, ms] of [...groups.entries()]) {
            if (ms.length < 2) {
                flat.push(...ms);
                groups.delete(series);
            }
        }
        const prefix = multiBrand ? (b + ' · ') : '';
        const bAttr = ` data-brand="${escapeHtml(b)}"`;
        if (groups.size) {
            for (const [series, ms] of groups.entries()) {
                out.push(`<option disabled value="" data-n="${ms.length}"${bAttr}>${escapeHtml(prefix + series)}</option>`);
                ms.forEach(m => out.push(opt(m)));
            }
            if (flat.length) {
                out.push(`<option disabled value="" data-n="${flat.length}"${bAttr}>${escapeHtml(prefix + t('other'))}</option>`);
                flat.forEach(m => out.push(opt(m)));
            }
        } else {
            if (multiBrand) out.push(`<option disabled value="" data-n="${flat.length}"${bAttr}>${escapeHtml(b)}</option>`);
            flat.forEach(m => out.push(opt(m)));
        }
    }
    return out.join('');
}

function onBrandChange() {
    const brand = document.getElementById('f-brand');
    const model = document.getElementById('f-model');
    const brands = Array.from(brand.selectedOptions).map(o => o.value).filter(Boolean);
    const totalBrands = Array.from(brand.options).filter(o => o.value).length;
    // models only mean something once you narrow to a few brands. "all brands"
    // or a near-complete set leaves the model dropdown empty and disabled
    const MODEL_MAX_BRANDS = 5;
    const narrowed = brands.length > 0 && brands.length < totalBrands && brands.length <= MODEL_MAX_BRANDS;
    const keep = new Set(Array.from(model.selectedOptions).map(o => o.value));
    // a newly-added brand starts with all its models included - adding a brand should
    // widen results, never silently exclude it through an unselected model subset
    const prevBrands = model._brands || [];
    for (const b of brands)
        if (!prevBrands.includes(b))
            for (const m of (_makes[b] || [])) keep.add(m);
    model.innerHTML = _buildModelOptions(narrowed ? brands : [], keep);
    model._brands = narrowed ? brands.slice() : [];
    model.disabled = !narrowed;
    // default: all models of the picked brand(s) are selected (none matched a prior
    // pick, like a fresh brand choice) and the user narrows down from there
    const opts = Array.from(model.options).filter(o => o.value);
    if (opts.length && !opts.some(o => o.selected)) opts.forEach(o => o.selected = true);
    if (model._cdd) model._cdd.render();
    updateFilterResets();
}

document.getElementById('f-brand').addEventListener('change', onBrandChange);
document.getElementById('f-model').addEventListener('change', updateFilterResets);

document.getElementById('f-sort').addEventListener('change', () => {
    if (document.body.classList.contains('mode-results')) doSearch();
});

document.getElementById('filter-sidebar').addEventListener('change', scheduleLiveCount);
const _mrange = document.getElementById('mileage-range');
if (_mrange) _mrange.addEventListener('input', scheduleLiveCount);
document.getElementById('search-input').addEventListener('input', scheduleLiveCount);

const ERROR_CODES = new Set([
    'query_too_vague', 'query_empty', 'phone_too_short',
    'car_invalid_key', 'car_not_found', 'cooldown', 'rate_limited',
]);

function errorMessage(detail) {
    if (detail && typeof detail === 'object' && ERROR_CODES.has(detail.code)) {
        return t('err_' + detail.code, detail);
    }
    return t('err_unknown');
}

function showSearchError(meta, message) {
    meta.innerHTML = '';
    const span = document.createElement('span');
    span.className = 'text-accent';
    span.textContent = message;
    meta.appendChild(span);
}

let _tpDone = null;

function startTopProgress() {
    const bar = document.getElementById('top-progress');
    if (!bar) return;
    clearTimeout(_tpDone);
    bar.style.transition = 'none';
    bar.style.transform = 'scaleX(0)';
    void bar.offsetWidth;
    bar.style.transition = 'transform 2.4s cubic-bezier(.08,.7,.2,1)';
    bar.style.transform = 'scaleX(0.9)'; // trickles toward 90% while the request is in flight
}

function finishTopProgress() {
    const bar = document.getElementById('top-progress');
    if (!bar) return;
    bar.style.transition = 'transform .25s ease';
    bar.style.transform = 'scaleX(1)'; // snaps to 100% and stays as the idle red line
}

function setOffline(off) {
    document.body.classList.toggle('is-offline', !!off);
}
window.addEventListener('offline', () => setOffline(true));
window.addEventListener('online', () => setOffline(false));
if (!navigator.onLine) setOffline(true);

const _URL_LISTS = {
    brand: 'manufacturers',
    model: 'models',
    body: 'body_types',
    fuel: 'fuels',
    gear: 'gearboxes',
    drive: 'drives',
    loc: 'locations'
};
const _URL_NUMS = {
    yf: 'year_from',
    yt: 'year_to',
    pf: 'price_from',
    pt: 'price_to',
    mf: 'mileage_from',
    mt: 'mileage_to'
};

function payloadToParams(p) {
    const sp = new URLSearchParams();
    if (p.query) sp.set('q', p.query);
    for (const [k, f] of Object.entries(_URL_LISTS))
        if (p[f] && p[f].length) sp.set(k, p[f].join('|'));
    for (const [k, f] of Object.entries(_URL_NUMS))
        if (p[f] != null) sp.set(k, p[f]);
    if (p.customs_cleared === true) sp.set('customs', 'yes');
    if (p.customs_cleared === false) sp.set('customs', 'no');
    if (p.sort) sp.set('sort', p.sort);
    if (p.page > 1) sp.set('page', p.page);
    return sp;
}

function paramsToPayload(sp) {
    const p = {};
    const q = (sp.get('q') || '').trim();
    if (q) p.query = q.slice(0, 200);
    for (const [k, f] of Object.entries(_URL_LISTS)) {
        const v = sp.get(k);
        // cap generously so an "all but a few" share/reload isn't silently narrowed;
        // the server still validates per-field, and a browser URL can't hold much more
        if (v) p[f] = v.split('|').map(s => s.trim()).filter(Boolean).slice(0, 300);
    }
    for (const [k, f] of Object.entries(_URL_NUMS)) {
        const n = parseInt(sp.get(k), 10);
        if (!Number.isNaN(n) && n >= 0) p[f] = n;
    }
    if (sp.get('customs') === 'yes') p.customs_cleared = true;
    if (sp.get('customs') === 'no') p.customs_cleared = false;
    const sort = sp.get('sort') || '';
    if (/^[a-z_]{1,24}$/.test(sort)) p.sort = sort;
    const page = parseInt(sp.get('page'), 10);
    if (page > 1 && page <= 200) p.page = page;
    return p;
}

function _syncUrl(payload) {
    if (parseRoute().view !== 'search') return;
    const qs = payloadToParams(payload).toString();
    const url = qs ? '/?' + qs : '/';
    if (location.pathname + location.search !== url) history.replaceState(history.state, '', url);
}

// one search at a time - a second Enter/click while a request is in flight would
// fire a duplicate POST whose cooldown-429 error wipes the results the first just drew
let _searchInFlight = false;
let _lastPayload = null; // last payload actually searched - used to restore the URL

async function doSearch(opts = {}) {
    if (_searchInFlight) return;
    if (opts.resetPage !== false) currentPage = 1;

    const payload = buildSearchPayload();
    const fields = Object.keys(payload).filter(k => k !== 'page');
    if (fields.length === 0) return;
    if (payload.query && fields.length === 1 &&
        payload.query.replace(/[^\p{L}\p{N}]/gu, '').length === 0) {
        document.body.classList.remove('mode-detail');
        document.body.classList.add('mode-results');
        document.getElementById('empty-state').classList.add('hidden');
        document.getElementById('results').innerHTML = '';
        showSearchError(document.getElementById('search-meta'), t('err_query_too_vague'));
        return;
    }
    pushHistory();
    _lastPayload = payload;
    _syncUrl(payload);

    const _ckey = JSON.stringify(payload);
    const _hit = _searchCache.get(_ckey);
    if (_hit && Date.now() - _hit.t < _SEARCH_TTL) {
        const cached = {
            ..._hit.data,
            remaining_searches: null
        };
        lastResponse = cached;
        document.body.classList.remove('mode-detail');
        document.body.classList.add('mode-results');
        document.getElementById('empty-state').classList.add('hidden');
        renderResults(cached);
        return;
    }

    const btn = document.getElementById('btn-search');
    const meta = document.getElementById('search-meta');
    const empty = document.getElementById('empty-state');
    const results = document.getElementById('results');

    _searchInFlight = true;
    btn.disabled = true;
    btn.textContent = t('btn_searching');
    document.querySelectorAll('[data-search-btn]').forEach(b => b.classList.add('is-busy'));
    meta.textContent = '';
    empty.classList.add('hidden');
    document.body.classList.remove('mode-detail');
    document.body.classList.add('mode-results');
    results.innerHTML = skeletonCards(currentPage === 1 ? 5 : 4); // loading state for every page
    startTopProgress();

    try {
        const resp = await fetch(`${API_BASE}/search`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-Client-Id': CLIENT_ID
            },
            body: JSON.stringify(payload),
        });

        if (!resp.ok) {
            let detail = null;
            try {
                detail = (await resp.json()).detail;
            } catch {}
            showSearchError(meta, errorMessage(detail));
            results.innerHTML = '';
            lastResponse = null;
            return;
        }

        lastResponse = await resp.json();
        setOffline(false);
        _searchCache.set(_ckey, {
            t: Date.now(),
            data: lastResponse
        });
        renderResults(lastResponse);
    } catch (e) {
        const offline = !navigator.onLine || e instanceof TypeError;
        if (offline) setOffline(true);
        results.innerHTML = '';
        showSearchError(meta, offline ? t('offline_msg') : t('err_fetch', {
            msg: e.message
        }));
    } finally {
        _searchInFlight = false;
        btn.disabled = false;
        document.querySelectorAll('[data-search-btn]').forEach(b => b.classList.remove('is-busy'));
        updateSearchBtnCount();
        finishTopProgress();
    }
}

document.getElementById('btn-search').onclick = () => doSearch();

document.querySelectorAll('#search-input, .filter-input, .filter-select').forEach((el) => {
    el.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') doSearch();
    });
});
document.querySelectorAll('.filter-input, .filter-select').forEach((el) => {
    el.addEventListener('change', updateFilterResets);
    el.addEventListener('input', updateFilterResets);
});

window.goToPage = function(page) {
    currentPage = page;
    doSearch({
        resetPage: false
    });
    // new page (the sticky sidebar keeps the filters pinned while scrolling results)
    window.scrollTo({
        top: 0,
        behavior: 'smooth'
    });
};

function escapeHtml(text) {
    return String(text == null ? '' : text)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function vinFromText(text) {
    if (!text) return '';
    const cleaned = String(text).toUpperCase().replace(/[A-Z0-9]*\*+[A-Z0-9*]*/g, ' ');
    const m = cleaned.match(/\b[A-HJ-NPR-Z0-9]{17}\b/);
    return m ? m[0] : '';
}

function phoneFromText(text) {
    if (!text) return '';
    const m = String(text).match(/(?:\+?\s?995[\s\-.]?)?5\d{2}(?:[\s\-.]?\d){6}/);
    if (!m) return '';
    let d = m[0].replace(/\D/g, '');
    if (d.startsWith('995')) d = d.slice(3);
    if (d.length !== 9 || d[0] !== '5') return '';
    return '+995 ' + d.slice(0, 3) + ' ' + d.slice(3, 6) + ' ' + d.slice(6);
}

function splitPhones(phone) {
    if (!phone) return [];
    const digits = phone.replace(/\D/g, '');
    if (digits.length <= 12) return [phone];

    const chunks = digits.match(/.{1,12}/g) || [];
    return chunks.map((c) => {
        if (c.length === 12 && c.startsWith('995')) {
            const m = c.substring(3);
            return `+995 ${m.substring(0, 3)} ${m.substring(3, 6)} ${m.substring(6)}`;
        }
        if (c.length === 9 && /^[573]/.test(c)) {
            return `+995 ${c.substring(0, 3)} ${c.substring(3, 6)} ${c.substring(6)}`;
        }
        return '+' + c;
    });
}

function youtubeId(url) {
    if (!url) return null;
    const m = url.match(/(?:v=|youtu\.be\/|embed\/)([\w-]{11})/);
    return m ? m[1] : null;
}

function formatDate(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    const locale = getLang() === 'ka' ? 'ka-GE' : 'en-GB';
    return d.toLocaleDateString(locale, {
        day: 'numeric',
        month: 'short',
        year: 'numeric'
    });
}

const _slidesByCard = {};

function slideStage(slide) {
    if (slide.type === 'video') {
        return `<iframe src="${escapeHtml(slide.src)}" allowfullscreen></iframe>`;
    }
    return `<img src="${escapeHtml(slide.src)}" alt="" loading="lazy" decoding="async" onerror="_photoFail(this)">`;
}

function thumbSrc(slide) {
    if (slide.type === 'video') {
        const id = (slide.src.match(/embed\/([\w-]+)/) || [])[1];
        return id ? `https://img.youtube.com/vi/${id}/default.jpg` : '';
    }
    return slide.src;
}

function photoBlockHtml(cardId, slides) {
    if (slides.length === 0) {
        return `<div class="no-photo w-full" style="aspect-ratio: 4 / 3;">${t('no_photos')}</div>`;
    }

    const counter = slides.length > 1 ?
        `<div class="carousel-counter" id="${cardId}-counter">${t('photo_counter', { i: 1, n: slides.length })}</div>` :
        '';

    const arrows = slides.length > 1 ? `
            <button class="ph-nav ph-prev" onclick="event.stopPropagation(); cardSlideBy('${cardId}', -1)" aria-label="prev">‹</button>
            <button class="ph-nav ph-next" onclick="event.stopPropagation(); cardSlideBy('${cardId}', 1)" aria-label="next">›</button>` : '';
    const main = `
        <div class="carousel w-full" id="${cardId}" data-index="0" onclick="openCardLightbox('${cardId}')">
            <div class="carousel-stage" id="${cardId}-stage">${slideStage(slides[0])}</div>
            ${arrows}
            ${counter}
        </div>
    `;

    return main;
}

window.cardSlideBy = function(cardId, delta) {
    const slides = _slidesByCard[cardId];
    if (!slides || !slides.length) return;
    const carousel = document.getElementById(cardId);
    let idx = (+carousel.dataset.index || 0) + delta;
    if (idx < 0) idx = slides.length - 1;
    if (idx >= slides.length) idx = 0;
    switchCardSlide(cardId, idx);
};

window.switchCardSlide = function(cardId, idx) {
    const slides = _slidesByCard[cardId];
    if (!slides || !slides[idx]) return;
    const carousel = document.getElementById(cardId);
    carousel.dataset.index = idx;
    document.getElementById(cardId + '-stage').innerHTML = slideStage(slides[idx]);
    const counter = document.getElementById(cardId + '-counter');
    if (counter) counter.textContent = t('photo_counter', {
        i: idx + 1,
        n: slides.length
    });
    const thumbs = carousel.parentElement.querySelectorAll('.thumb');
    thumbs.forEach((el, i) => el.classList.toggle('is-active', i === idx));
};

window.openCardLightbox = function(cardId) {
    const slides = _slidesByCard[cardId];
    if (!slides || !slides.length) return;
    const carousel = document.getElementById(cardId);
    const idx = parseInt(carousel.dataset.index, 10) || 0;
    openLightbox(slides, idx);
};

let _lightbox = null;

window.openLightbox = function(slides, startIdx) {
    _lightbox = {
        slides,
        idx: Math.max(0, Math.min(startIdx || 0, slides.length - 1))
    };
    lockScroll('lightbox');
    renderLightbox();
    document.getElementById('lightbox').classList.remove('hidden');
};

window.closeLightbox = function() {
    document.getElementById('lightbox').classList.add('hidden');
    document.getElementById('lightbox-stage').innerHTML = '';
    unlockScroll('lightbox');
    _lightbox = null;
};

// touch swipe, left and right
function addSwipe(el, onLeft, onRight) {
    if (!el) return;
    let x0 = null,
        y0 = null;
    el.addEventListener('touchstart', (e) => {
        x0 = e.touches[0].clientX;
        y0 = e.touches[0].clientY;
    }, {
        passive: true
    });
    el.addEventListener('touchend', (e) => {
        if (x0 == null) return;
        const dx = e.changedTouches[0].clientX - x0;
        const dy = e.changedTouches[0].clientY - y0;
        if (Math.abs(dx) > 45 && Math.abs(dx) > Math.abs(dy) * 1.4) {
            dx < 0 ? onLeft() : onRight();
        }
        x0 = y0 = null;
    }, {
        passive: true
    });
}
addSwipe(document.getElementById('lightbox-stage'), () => lightboxGo(1), () => lightboxGo(-1));

window.lightboxGo = function(delta) {
    if (!_lightbox) return;
    let idx = _lightbox.idx + delta;
    if (idx < 0) idx = _lightbox.slides.length - 1;
    if (idx >= _lightbox.slides.length) idx = 0;
    _lightbox.idx = idx;
    renderLightbox();
};

window.lightboxJump = function(idx) {
    if (!_lightbox) return;
    _lightbox.idx = idx;
    renderLightbox();
};

function renderLightbox() {
    const {
        slides,
        idx
    } = _lightbox;
    const stage = document.getElementById('lightbox-stage');
    stage.innerHTML = slideStage(slides[idx]);
    const sImg = stage.querySelector('img');
    if (sImg) sImg.classList.add('photo-anim'); // fade/zoom in on switch
    document.getElementById('lightbox-counter').textContent = t('photo_counter', {
        i: idx + 1,
        n: slides.length
    });

    const thumbs = document.getElementById('lightbox-thumbs');
    thumbs.innerHTML = slides.map((s, i) => `
        <button class="lightbox-thumb ${i === idx ? 'is-active' : ''}" onclick="lightboxJump(${i})">
            <img src="${escapeHtml(thumbSrc(s))}" alt="">
        </button>
    `).join('');

    const active = thumbs.querySelector('.lightbox-thumb.is-active');
    if (active) active.scrollIntoView({
        inline: 'center',
        block: 'nearest',
        behavior: 'smooth'
    });
}

document.addEventListener('keydown', (e) => {
    if (!_lightbox) return;
    if (e.key === 'Escape') closeLightbox();
    else if (e.key === 'ArrowLeft') lightboxGo(-1);
    else if (e.key === 'ArrowRight') lightboxGo(1);
});

function paginationHtml(data) {
    const totalPages = Math.max(1, Math.ceil(data.total_count / data.page_size));
    if (totalPages <= 1) return '';
    const prevDisabled = data.page <= 1 ? 'disabled' : '';
    const nextDisabled = data.page >= totalPages ? 'disabled' : '';
    return `
        <div class="pager">
            <button class="pager-btn" ${prevDisabled}
                    onclick="goToPage(${data.page - 1})">${t('page_prev')}</button>
            <span class="pager-info">${t('page_of', { p: data.page, n: totalPages })}</span>
            <button class="pager-btn" ${nextDisabled}
                    onclick="goToPage(${data.page + 1})">${t('page_next')}</button>
        </div>
    `;
}

function skeletonCards(n) {
    let s = '';
    for (let i = 0; i < n; i++) {
        s += '<div class="skeleton-card"><div class="sk sk-img"></div>' +
            '<div class="sk-body">' +
            '<div class="sk sk-line" style="width:55%"></div>' +
            '<div class="sk sk-line" style="width:32%;height:22px"></div>' +
            '<div class="sk sk-line" style="width:85%"></div>' +
            '<div class="sk sk-line" style="width:72%"></div></div></div>';
    }
    return s;
}

function carTitle(car) {
    const words = [car.manufacturer, car.model].filter(Boolean).join(' ').split(/\s+/);
    const seen = new Set();
    const out = [];
    for (const w of words) {
        const k = w.toLowerCase();
        if (k && !seen.has(k)) {
            seen.add(k);
            out.push(w);
        }
    }
    let title = out.join(' ');
    if (car.year) title += ' ' + car.year;
    return title;
}

const _PIC = (d) => `<svg class="pill-ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${d}</svg>`;
const _PILL_IC = {
    gauge: _PIC('<path d="M13.4 13.4l2.6 -2.6"/><path d="M3.6 15a9 9 0 1 1 16.8 0"/>'),
    engine: _PIC('<rect x="3.5" y="10" width="11" height="7" rx="1.2"/><path d="M6 10V7.5h2V10M10 10V7.5h2V10"/><path d="M14.5 12h2.2l2.3 2.3v.6L16.7 17h-2.2"/><path d="M3.5 13.5H2M8 17v1.8"/>').replace('<svg ', '<svg data-ic="engine" '),
    bolt: _PIC('<path d="M13 3l-9 11h7l-1 7l9 -11h-7z"/>'),
};

function _bodyIcon(v) {
    const s = (v || '').toLowerCase();
    if (/კუპე|coupe/.test(s)) // fastback 2-door
        return _PIC('<path d="M3 15h18"/><path d="M4 15v-1.3l3.2-3.3c2.3-1.8 8.2-1.6 11.3.6l.9.7a1.3 1.3 0 0 1 .6 1V15"/><path d="M7.3 10.4c3-1.4 7.6-1.4 10.6.6" stroke-width="1.2" opacity=".65"/><circle cx="7.5" cy="15.5" r="1.6"/><circle cx="16.5" cy="15.5" r="1.6"/>');
    if (/სპორტ|sport/.test(s)) // low wide wedge
        return _PIC('<path d="M1.5 15.6h21"/><path d="M2.6 15.6l.8-2 4.2-.6 2.2-2.1c1.8-.5 4.8-.4 6.4.7l2.8 1.8 2.3.4.5 1.8"/><circle cx="7.2" cy="15.9" r="1.5"/><circle cx="16.8" cy="15.9" r="1.5"/>');
    if (/კაბრ|convert|როდსტ|cabrio/.test(s)) // open top - windshield only
        return _PIC('<path d="M3 15h18"/><path d="M4.3 15l1.3-3.4A2 2 0 0 1 7.5 10.3h9a2 2 0 0 1 1.9 1.3L19.7 15"/><path d="M8 10.3l2-2.6" stroke-width="1.3"/><circle cx="7.5" cy="15.5" r="1.6"/><circle cx="16.5" cy="15.5" r="1.6"/>');
    if (/ჰეტ|ჰეჩ|hatch|ლიფტ/.test(s)) // sloped rear hatch
        return _PIC('<path d="M3 15h18"/><path d="M4.5 15v-2.6l1.7-3A2 2 0 0 1 8 8.4h4.4l4.8 4h1.3a1.3 1.3 0 0 1 1.3 1.3V15"/><path d="M12.4 8.4V12.4H4.5"/><circle cx="7.5" cy="15.5" r="1.6"/><circle cx="16.5" cy="15.5" r="1.6"/>');
    if (/ჯიპ|jeep/.test(s)) // boxy upright SUV
        return _PIC('<path d="M3 16h18"/><path d="M4.5 16V9.6A1.3 1.3 0 0 1 5.8 8.3h8.4a1.3 1.3 0 0 1 1 .5l2.3 2.9h.9a1.2 1.2 0 0 1 1.1 1.2V16"/><path d="M4.5 12h14.5M9.5 8.3V12M13.8 8.3V12"/><circle cx="7.5" cy="16.5" r="1.7"/><circle cx="16.5" cy="16.5" r="1.7"/>');
    if (/ყველგ|off.?road/.test(s)) // rugged - roof rack + rear spare
        return _PIC('<path d="M2.5 16h16.3"/><path d="M4 16V10A1.3 1.3 0 0 1 5.3 8.7h7.9a1.3 1.3 0 0 1 1 .5l2 2.6h1a1.2 1.2 0 0 1 1.2 1.2V16"/><path d="M4.7 8.1h8.5M4.5 12h13"/><circle cx="7.3" cy="16.5" r="1.8"/><circle cx="15.4" cy="16.5" r="1.8"/><path d="M19 13.2v3.3" stroke-width="1.5"/>');
    if (/კროსოვ|cross|\bsuv\b/.test(s)) // rounded crossover
        return _PIC('<path d="M3 16h18"/><path d="M4.3 16v-3.6l1.9-3A2 2 0 0 1 7.9 8.5h6.4a2 2 0 0 1 1.6.8l2.3 3.1h.5a1.3 1.3 0 0 1 1 1.3V16"/><path d="M4.5 12.2h14.5M11.5 8.5V12.2"/><circle cx="7.5" cy="16.5" r="1.7"/><circle cx="16.5" cy="16.5" r="1.7"/>');
    if (/უნივ|wagon|estate/.test(s)) // long flat roof
        return _PIC('<path d="M3 15h18"/><path d="M4.3 15v-4.4l1.6-2.2A2 2 0 0 1 7.5 7.6h9.6a1.4 1.4 0 0 1 1.4 1.4V15"/><path d="M4.3 11h14.2M9 7.6V11"/><circle cx="7.5" cy="15.5" r="1.6"/><circle cx="16.5" cy="15.5" r="1.6"/>');
    if (/მიკრო|ავტობუს|\bbus\b/.test(s)) // boxy bus, window row
        return _PIC('<path d="M2 16.5h20"/><rect x="3.3" y="6" width="17.4" height="10.5" rx="1.6"/><path d="M3.3 10.2h17.4M8 6v4.2M13.2 6v4.2"/><circle cx="7" cy="16.5" r="1.7"/><circle cx="17" cy="16.5" r="1.7"/>');
    if (/მინივ|minivan|ფურგ|\bvan\b/.test(s)) // one-box minivan, sloped nose
        return _PIC('<path d="M3 16h18"/><path d="M4.3 16V9.6A1.4 1.4 0 0 1 5.7 8.2h9.9l3 3.2a1.4 1.4 0 0 1 .4 1V16"/><path d="M4.3 12.4h14.7M9 8.2V12.4M13.5 8.4V12.4"/><circle cx="7.5" cy="16.5" r="1.7"/><circle cx="16.5" cy="16.5" r="1.7"/>');
    if (/პიკაპ|pickup/.test(s)) // cab + open bed
        return _PIC('<path d="M2.5 16h19"/><path d="M4 16v-4h6.2l1.4-3h3.2l1.4 3H20v4"/><path d="M4.3 12h6.2V9.2"/><circle cx="7.5" cy="16.5" r="1.7"/><circle cx="16.5" cy="16.5" r="1.7"/>');
    if (/სატვირთ|truck/.test(s)) // cargo box truck
        return _PIC('<path d="M2 16h20"/><path d="M2.6 16V9h8v7M10.6 11h4l3 3v2h-2"/><path d="M2.6 12.5h8"/><circle cx="6" cy="16.8" r="1.6"/><circle cx="16.5" cy="16.8" r="1.6"/>');
    if (/კვადრო|atv|quad|ბაგ/.test(s)) // ATV - fat tyres + handlebar
        return _PIC('<circle cx="5.6" cy="16" r="2.9"/><circle cx="18.4" cy="16" r="2.9"/><path d="M5.6 16l1.9-4.2h5.6l2.7 3.4"/><path d="M13.1 11.8l-1.4-2.6M10.4 9.2h3.4M7.5 11.8l1.4-2"/>');
    if (/სპეცტ|special|ექსკავ|ტექნიკ|ამწე/.test(s)) // construction loader
        return _PIC('<path d="M3 17v-4h7v4"/><path d="M10 14l4-1 5 3v1h-2"/><path d="M10 13L7 9h2"/><circle cx="6" cy="17.5" r="1.6"/><circle cx="16" cy="17.5" r="1.6"/>');
    return _PIC('<path d="M3 15h18"/><path d="M4.2 15l1.3-3.4A2 2 0 0 1 7.4 10.3h9.2a2 2 0 0 1 1.9 1.3L19.8 15"/><path d="M6.8 10.3l1-1.9A1.5 1.5 0 0 1 9.1 7.6h5.8a1.5 1.5 0 0 1 1.3.8l1 1.9"/><circle cx="7.5" cy="15.5" r="1.6"/><circle cx="16.5" cy="15.5" r="1.6"/>');
}

function _fuelIcon(v) {
    const s = (v || '').toLowerCase();
    if (/ელექტ|electric|\bev\b/.test(s)) // bolt
        return _PIC('<path d="M13 3l-9 11h7l-1 7l9-11h-7z"/>');
    if (/დატენ|plug|phev/.test(s)) // charger plug (plug-in hybrid)
        return _PIC('<path d="M8.5 3v3.5M15.5 3v3.5"/><path d="M6.5 6.5h11v3a5.5 5.5 0 0 1-11 0z"/><path d="M12 15V21M9.5 21h5"/>');
    if (/ჰიბრ|hybrid/.test(s)) // droplet + bolt
        return _PIC('<path d="M12 3.3c2.9 3.9 4.7 6.1 4.7 8.7a4.7 4.7 0 0 1-9.4 0c0-2.6 1.8-4.8 4.7-8.7z"/><path d="M12.4 8.8l-2 3.4h2.5l-1.5 3" stroke-width="1.3"/>');
    if (/დიზ|diesel/.test(s)) // jerry can
        return _PIC('<path d="M4 8.5h10a1 1 0 0 1 1 1v7.5a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2z"/><path d="M15 11h2.6l1.4 1.5V16"/><path d="M6.5 8.5V6.5h4.5v2M7 12h6"/>');
    if (/თხევად|lpg|პროპან/.test(s)) // horizontal LPG cylinder
        return _PIC('<rect x="3" y="9" width="14.5" height="6.5" rx="3.25"/><path d="M17.5 11h2.5M17.5 13.5h2.5M6.5 9V7.2h4V9"/>');
    if (/ბუნებრივ|cng|მეთან|methane/.test(s)) // vertical CNG bottle
        return _PIC('<path d="M8.5 21V10a3.5 3.5 0 0 1 7 0v11z"/><path d="M8.5 21h7M10 6.5h4M11 4.5h2v2h-2z"/>');
    if (/გაზ|gas/.test(s)) // ბენზინი/გაზი - droplet + flame
        return _PIC('<path d="M7.5 5c1.9 2.2 3 3.6 3 5.1a3 3 0 0 1-6 0c0-1.5 1.1-2.9 3-5.1z"/><path d="M17 5.5c2 2.3 2.8 3.9 2.8 5.5a2.8 2.8 0 0 1-5.6 0c0-1.1.5-2.2 1.4-3.3.2 1 .8 1.5 1.7 1.5 0-1.2-.4-2.4-.3-3.7z"/>');
    return _PIC('<path d="M6 21V5.5A2.5 2.5 0 0 1 8.5 3h3A2.5 2.5 0 0 1 14 5.5V21"/><path d="M4 21h12M8 8h4"/><path d="M14 9l2.4 2.4c.4.4.6.9.6 1.4V17a1.5 1.5 0 0 0 3 0V9.5L17 6.5"/>');
}

function _gearIcon(v) {
    const s = (v || '').toLowerCase();
    if (/ტიპტ|tiptron|სტეპტ|steptron|დსგ|\bdsg\b|რობ|robot/.test(s))
        return _PIC('<rect x="5" y="3" width="9" height="18" rx="2"/><circle cx="9.5" cy="7" r="1"/><circle cx="9.5" cy="12" r="1"/><circle cx="9.5" cy="17" r="1"/><path d="M17 7.5h3M18.5 6v3M17 16.5h3"/>');
    if (/მექ|manual|\bmt\b/.test(s))
        return _PIC('<circle cx="6" cy="5" r="1.6"/><circle cx="12" cy="5" r="1.6"/><circle cx="18" cy="5" r="1.6"/><path d="M6 6.6v4h12v-4M12 10.6v8.4M10 19h4"/>');
    if (/ვარიატ|variator|\bcvt\b/.test(s))
        return _PIC('<path d="M4 5l4.5 3.5v7L4 19z"/><path d="M20 5l-4.5 3.5v7L20 19z"/><path d="M8.5 8.5h7M8.5 15.5h7"/>');
    return _PIC('<rect x="7" y="3" width="10" height="18" rx="2"/><circle cx="12" cy="6.5" r="1"/><circle cx="12" cy="10" r="1"/><circle cx="12" cy="13.5" r="1"/><circle cx="12" cy="17" r="1"/>');
}

function _driveIcon(v) {
    const s = (v || '').toLowerCase();
    const on = '',
        off = ' opacity=".35"';
    let tl = on,
        tr = on,
        bl = on,
        br = on;
    if (/4x4|4wd|awd|ოთხ|სრულ|all|სავ/.test(s)) {
        /* ყველა მუქი */ } else if (/უკან|rear|\brwd\b|უკანა/.test(s)) {
        tl = off;
        tr = off;
    } else {
        bl = off;
        br = off;
    } // წინა (default)
    return _PIC(`<circle cx="6.5" cy="7" r="2.5"${tl}/><circle cx="17.5" cy="7" r="2.5"${tr}/><circle cx="6.5" cy="17" r="2.5"${bl}/><circle cx="17.5" cy="17" r="2.5"${br}/><path d="M6.5 7v10M17.5 7v10" opacity=".45"/>`);
}

function _mileageGauge(km) {
    const frac = Math.max(0, Math.min(1, (km || 0) / 500000));
    const ang = Math.PI * (1 - frac);
    const cx = 12,
        cy = 15.5,
        r = 7;
    const nx = (cx + r * Math.cos(ang)).toFixed(1);
    const ny = (cy - r * Math.sin(ang)).toFixed(1);
    return `<svg class="pill-ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 15.5a8 8 0 0 1 16 0"/><line class="mg-needle" x1="${cx}" y1="${cy}" x2="${nx}" y2="${ny}"/><circle cx="${cx}" cy="${cy}" r="1.1" fill="currentColor" stroke="none"/></svg>`;
}

function _sortIcon(v) {
    const val = v || '';
    const bars = /asc/.test(val) ?
        '<path d="M15 17v-2.5M18 17v-5M21 17v-7.5"/>' :
        '<path d="M15 17v-7.5M18 17v-5M21 17v-2.5"/>';
    if (/^price/.test(val)) return _PIC('<rect x="2" y="8.5" width="10.5" height="7" rx="1.2"/><circle cx="7.2" cy="12" r="1.7"/>' + bars);
    if (/^year/.test(val)) return _PIC('<rect x="2.5" y="8" width="9" height="8" rx="1.3"/><path d="M2.5 10.6h9M5.2 6.4v3M8.8 6.4v3"/>' + bars);
    if (/^mileage/.test(val)) return _PIC('<path d="M2.4 14.2a5.2 5.2 0 0 1 10.4 0"/><path d="M7.6 14.2l2.1-2.1"/><circle cx="7.6" cy="14.2" r=".85" fill="currentColor" stroke="none"/>' + bars);
    return _PIC('<path d="M4 7h13M4 12h9M4 17h5"/>'); // default (newest)
}

function _customsIcon(val) {
    const shield = '<path d="M12 3l7 3v5c0 4.4-3 7.7-7 9-4-1.3-7-4.6-7-9V6z"/>';
    if (val === 'yes') return _PIC(shield + '<path d="M9 12l2 2 4-4"/>');
    if (val === 'no') return _PIC(shield + '<path d="M9.5 9.5l5 5M14.5 9.5l-5 5"/>');
    return '';
}

const _CYR = {
    'а': 'a',
    'б': 'b',
    'в': 'v',
    'г': 'g',
    'д': 'd',
    'е': 'e',
    'ё': 'e',
    'ж': 'zh',
    'з': 'z',
    'и': 'i',
    'й': 'i',
    'к': 'k',
    'л': 'l',
    'м': 'm',
    'н': 'n',
    'о': 'o',
    'п': 'p',
    'р': 'r',
    'с': 's',
    'т': 't',
    'у': 'u',
    'ф': 'f',
    'х': 'h',
    'ц': 'c',
    'ч': 'ch',
    'ш': 'sh',
    'щ': 'sch',
    'ъ': '',
    'ы': 'i',
    'ь': '',
    'э': 'e',
    'ю': 'iu',
    'я': 'ia'
};
const _GEO = {
    'ა': 'a',
    'ბ': 'b',
    'გ': 'g',
    'დ': 'd',
    'ე': 'e',
    'ვ': 'v',
    'ზ': 'z',
    'თ': 't',
    'ი': 'i',
    'კ': 'k',
    'ლ': 'l',
    'მ': 'm',
    'ნ': 'n',
    'ო': 'o',
    'პ': 'p',
    'ჟ': 'zh',
    'რ': 'r',
    'ს': 's',
    'ტ': 't',
    'უ': 'u',
    'ფ': 'p',
    'ქ': 'k',
    'ღ': 'gh',
    'ყ': 'k',
    'შ': 'sh',
    'ჩ': 'ch',
    'ც': 'c',
    'ძ': 'dz',
    'წ': 'c',
    'ჭ': 'ch',
    'ხ': 'h',
    'ჯ': 'j',
    'ჰ': 'h'
};

function _translit(str) {
    let out = '';
    for (const ch of String(str).toLowerCase()) out += (_CYR[ch] != null ? _CYR[ch] : (_GEO[ch] != null ? _GEO[ch] : ch));
    return out;
}

function _searchCanon(str) {
    return _translit(str).replace(/[^a-z0-9]/g, '').replace(/c/g, 'k').replace(/y/g, 'i').replace(/w/g, 'v').replace(/(.)\1+/g, '$1');
}

function _matchFilter(text, filter) {
    const t = text.toLowerCase();
    if (t.includes(filter)) return true; // same-script substring
    return _searchCanon(text).includes(_searchCanon(filter)); // cross-script / fuzzy
}

function carSpecPills(car) {
    const en = getLang() === 'en';
    const pills = [];
    if (car.body_type) pills.push(['body', _bodyIcon(car.body_type), tval(car.body_type)]);
    if (car.mileage_km) pills.push(['mileage', _mileageGauge(car.mileage_km), car.mileage_km.toLocaleString() + (en ? ' km' : ' კმ')]);
    if (car.engine_volume_l) pills.push(['engine', _PILL_IC.engine, car.engine_volume_l + ' L']);
    if (car.power_hp) pills.push(['power', _PILL_IC.bolt, car.power_hp + (en ? ' hp' : ' ც.ძ.')]);
    if (car.engine_type) pills.push(['fuel', _fuelIcon(car.engine_type), tval(car.engine_type)]);
    if (car.gearbox) pills.push(['gearbox', _gearIcon(car.gearbox), tval(car.gearbox)]);
    if (car.drive_wheels) pills.push(['drive', _driveIcon(car.drive_wheels), tval(car.drive_wheels)]);
    return pills.map(([type, ic, x]) => `<span class="spec-pill" data-ic="${type}">${ic}${escapeHtml(x)}</span>`).join('');
}

function customsBadgeHtml(car) {
    if (car.customs_cleared === true)
        return `<span class="customs-badge customs-yes"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12l4 4l10 -11"/></svg>${t('cleared')}</span>`;
    if (car.customs_cleared === false)
        return `<span class="customs-badge customs-no"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M18 6l-12 12M6 6l12 12"/></svg>${t('not_cleared')}</span>`;
    return '';
}

function sourceBadgeHtml(car) {
    const name = car.source === 'myauto' ? 'myauto.ge' : car.source === 'autopapa' ? 'autopapa.ge' : car.source;
    return `<span class="source-badge source-${escapeHtml(car.source)}">${escapeHtml(name)}</span>`;
}

const ICON_HIDE = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 3l18 18"/><path d="M10.6 10.7a2 2 0 0 0 2.7 2.7"/><path d="M16.7 16.7A9 9 0 0 1 12 18c-5 0-8.3-4-9-6a14 14 0 0 1 3.3-3.8"/><path d="M9.9 5.2A9 9 0 0 1 12 5c5 0 8.3 4 9 6a14 14 0 0 1-1.6 2.4"/></svg>';
const HIDDEN_KEY = 'cdb_hidden';

function getHiddenList() {
    try {
        return JSON.parse(localStorage.getItem(HIDDEN_KEY) || '[]').map(x => typeof x === 'string' ? {
            key: x
        } : x);
    } catch {
        return [];
    }
}

function setHiddenList(list) {
    try {
        localStorage.setItem(HIDDEN_KEY, JSON.stringify(list));
    } catch {}
}

function getHidden() {
    return new Set(getHiddenList().map(x => x.key));
} // key set, used to filter results

window.hideCar = function(key, btn) {
    const list = getHiddenList();
    if (!list.some(x => x.key === key)) {
        const d = _carData[key] || {};
        list.push({
            key,
            title: d.title || key,
            thumb: d.thumb || ''
        });
        setHiddenList(list);
    }
    const card = btn.closest('.rcard');
    if (card) {
        card.classList.add('is-hiding');
        setTimeout(() => {
            card.remove();
            if (lastResponse && !document.querySelector('#results .rcard')) renderResults(lastResponse);
        }, 290);
    }
    showToast(t('toast_hidden'), t('act_undo'), () => {
        setHiddenList(getHiddenList().filter(x => x.key !== key));
        if (lastResponse) renderResults(lastResponse);
    });
};
window.unhideCar = function(key) {
    setHiddenList(getHiddenList().filter(x => x.key !== key));
    renderSaved();
    if (lastResponse) renderResults(lastResponse);
};
window.clearHidden = function() {
    setHiddenList([]);
    renderSaved();
    if (lastResponse) renderResults(lastResponse);
};

let _toastTimer = null;

function showToast(msg, actionLabel, actionFn) {
    let el = document.getElementById('toast');
    if (!el) {
        el = document.createElement('div');
        el.id = 'toast';
        el.className = 'toast';
        el.setAttribute('role', 'status');
        el.setAttribute('aria-live', 'polite');
        document.body.appendChild(el);
    }
    el.innerHTML = '<span></span>' + (actionLabel ? '<button type="button"></button>' : '');
    el.querySelector('span').textContent = msg;
    if (actionLabel) {
        const b = el.querySelector('button');
        b.textContent = actionLabel;
        b.onclick = () => {
            if (actionFn) actionFn();
            hideToast();
        };
    }
    el.classList.remove('show');
    void el.offsetWidth;
    el.classList.add('show');
    clearTimeout(_toastTimer);
    _toastTimer = setTimeout(hideToast, 4500);
}

function hideToast() {
    const el = document.getElementById('toast');
    if (el) el.classList.remove('show');
}

const ICON_COMPARE = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M7 4v16M17 4v16M3 8l4-4 4 4M21 16l-4 4-4-4"/></svg>';
const ICON_HEART = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.6l-1-1a5.5 5.5 0 0 0-7.8 7.8l1 1L12 21l7.8-7.6 1-1a5.5 5.5 0 0 0 0-7.8z"/></svg>';
const COMPARE_KEY = 'cdb_compare';
const _carFull = {};

function getCompare() {
    try {
        const v = JSON.parse(localStorage.getItem(COMPARE_KEY) || '[]');
        return Array.isArray(v) ? v : [];
    } catch {
        return [];
    }
}

function setCompare(list) {
    try {
        localStorage.setItem(COMPARE_KEY, JSON.stringify(list));
    } catch {}
}

function isInCompare(key) {
    return getCompare().some(c => c.key === key);
}

function summarizeCar(car) {
    return {
        key: `${car.source}-${car.source_id}`,
        title: carTitle(car),
        price: car.price_amount,
        currency: car.price_currency,
        year: car.year,
        mileage: car.mileage_km,
        engine: car.engine_volume_l,
        power: car.power_hp,
        fuel: car.engine_type,
        gearbox: car.gearbox,
        drive: car.drive_wheels,
        body: car.body_type,
        location: car.location,
        customs: car.customs_cleared,
        thumb: (car.image_urls && car.image_urls[0]) || '',
        url: `/car/${car.source}-${car.source_id}`,
    };
}
window.toggleCompare = function(carKey, btn) {
    const list = getCompare();
    const idx = list.findIndex(c => c.key === carKey);
    if (idx >= 0) {
        list.splice(idx, 1);
        if (btn) {
            btn.classList.remove('on');
            btn.setAttribute('aria-pressed', 'false');
        }
    } else {
        if (list.length >= 4) {
            showToast(t('compare_max'));
            return;
        }
        const car = _carFull[carKey];
        if (!car) return;
        list.push(summarizeCar(car));
        if (btn) {
            btn.classList.add('on');
            btn.setAttribute('aria-pressed', 'true');
            btn.classList.remove('pop');
            void btn.offsetWidth;
            btn.classList.add('pop');
        }
    }
    setCompare(list);
    renderCompareBar();
};

function renderCompareBar() {
    let bar = document.getElementById('cmp-bar');
    const list = getCompare();
    document.body.classList.toggle('has-cmpbar', list.length > 0);
    if (!bar) {
        bar = document.createElement('div');
        bar.id = 'cmp-bar';
        bar.className = 'cmp-bar';
        document.body.appendChild(bar);
    }
    if (!list.length) {
        bar.classList.remove('show');
        bar.innerHTML = '';
        return;
    }
    const thumbs = list.map(c =>
        `<span class="cmp-thumb-wrap" title="${escapeHtml(c.title)}" onclick="goToCarDetail('${escapeHtml(c.key)}', event)">` +
        _cmpImg(c.thumb, 'cmp-thumb') +
        `<button class="cmp-thumb-x" onclick="event.stopPropagation(); removeFromCompare('${escapeHtml(c.key)}')" aria-label="${escapeHtml(t('remove'))}">✕</button></span>`
    ).join('');
    bar.innerHTML =
        `<span class="cmp-bar-label">${t('compare_title')} · ${list.length}</span>` +
        `<div class="cmp-bar-thumbs">${thumbs}</div>` +
        `<button class="cmp-bar-open" onclick="openCompare()">${t('act_compare')}</button>` +
        `<button class="cmp-bar-clear" onclick="clearCompare()">${t('compare_clear')}</button>`;
    bar.classList.add('show');
}
window.clearCompare = function() {
    setCompare([]);
    renderCompareBar();
    document.querySelectorAll('.rcard-compare.on').forEach(b => {
        b.classList.remove('on');
        b.setAttribute('aria-pressed', 'false');
    });
    closeCompare();
};
window.removeFromCompare = function(key) {
    const list = getCompare().filter(c => c.key !== key);
    setCompare(list);
    const btn = document.querySelector(`.rcard-compare[data-key="${(window.CSS && CSS.escape) ? CSS.escape(key) : key}"]`);
    if (btn) {
        btn.classList.remove('on');
        btn.setAttribute('aria-pressed', 'false');
    }
    renderCompareBar();
    if (list.length) renderCompareModal();
    else closeCompare();
};
const CMPSAVE_KEY = 'cdb_compsaves';

function getCompSaves() {
    try {
        const v = JSON.parse(localStorage.getItem(CMPSAVE_KEY) || '[]');
        return Array.isArray(v) ? v : [];
    } catch {
        return [];
    }
}

function setCompSaves(l) {
    try {
        localStorage.setItem(CMPSAVE_KEY, JSON.stringify(l));
    } catch {}
}

function _cmpSetKey(cars) {
    return (cars || []).map(c => c.key).slice().sort().join('|');
}

function _isComparisonSaved(cars) {
    const k = _cmpSetKey(cars);
    return getCompSaves().some(s => _cmpSetKey(s.cars) === k);
}

function _syncCmpSaveBtn() {
    const btn = document.querySelector('#cmp-modal .cmp-save-btn');
    if (btn) btn.style.display = _isComparisonSaved(getCompare()) ? 'none' : '';
}
window.saveComparison = function() {
    const list = getCompare();
    if (list.length < 2) return;
    if (_isComparisonSaved(list)) {
        _syncCmpSaveBtn();
        return;
    } // no duplicate saves
    setCompSaves([{
        cars: list
    }, ...getCompSaves()].slice(0, 12));
    updateSavedCount();
    showToast(t('saved_done'));
    _syncCmpSaveBtn();
};
window.loadComparison = function(i) {
    const s = getCompSaves()[i];
    if (!s) return;
    setCompare(s.cars);
    closeSaved();
    document.querySelectorAll('.rcard-compare').forEach(b => {
        const on = s.cars.some(c => c.key === b.dataset.key);
        b.classList.toggle('on', on);
        b.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
    renderCompareBar();
    openCompare();
};
window.deleteComparison = function(i) {
    const saves = getCompSaves();
    saves.splice(i, 1);
    setCompSaves(saves);
    updateSavedCount();
    renderSaved();
};

function _driveScore(d) {
    const s = (d || '').toLowerCase();
    return /4x4|4wd|awd|ოთხ|სრულ|толық|полн/.test(s) ? 2 : 1;
}
const _CMP_FACTORS = [{
        weight: 3,
        better: 'high',
        ref: 8,
        val: c => c.year || null
    },
    {
        weight: 3,
        better: 'low',
        ref: 150000,
        val: c => c.mileage || null
    },
    {
        weight: 3,
        better: 'low',
        ref: 'mean',
        val: c => c.price > 0 ? c.price : null
    },
    {
        weight: 1,
        better: 'high',
        ref: 80,
        val: c => c.power || null
    },
    {
        weight: 1,
        better: 'high',
        ref: 1,
        val: c => c.drive ? _driveScore(c.drive) : null
    },
    {
        weight: 1,
        better: 'high',
        ref: 1,
        val: c => c.customs === true ? 1 : c.customs === false ? 0 : null
    },
];

function _cmpScores(list) {
    const scores = list.map(() => 0);
    for (const f of _CMP_FACTORS) {
        const vals = list.map(f.val);
        const present = vals.filter(v => v != null);
        if (present.length < 2) continue;
        const max = Math.max(...present),
            min = Math.min(...present);
        if (max === min) continue;
        const ref = f.ref === 'mean' ? present.reduce((a, b) => a + b, 0) / present.length : f.ref;
        const gapScale = Math.min(1, (max - min) / ref);
        for (let i = 0; i < list.length; i++) {
            if (vals[i] == null) continue;
            let adv = (vals[i] - min) / (max - min);
            if (f.better === 'low') adv = 1 - adv;
            scores[i] += f.weight * gapScale * adv;
        }
    }
    return scores;
}

function _compareSummary(list, scores) {
    let bi = 0;
    for (let i = 1; i < list.length; i++)
        if (scores[i] > scores[bi]) bi = i;
    const sorted = [...scores].sort((a, b) => b - a);
    if (!sorted[0]) return '';
    const margin = sorted[0] - (sorted[1] || 0);
    if (margin < 0.4) return t('cmp_close_call');
    const w = list[bi];
    const uniqMax = (f) => {
        const vs = list.map(f).filter(v => v != null);
        if (vs.length < 2) return false;
        const m = Math.max(...vs);
        return f(w) === m && vs.filter(v => v === m).length === 1;
    };
    const uniqMin = (f) => {
        const vs = list.map(f).filter(v => v != null);
        if (vs.length < 2) return false;
        const m = Math.min(...vs);
        return f(w) === m && vs.filter(v => v === m).length === 1;
    };
    const reasons = [];
    if (uniqMax(c => c.year || null)) reasons.push(t('cmp_reason_newer'));
    if (uniqMin(c => c.mileage || null)) reasons.push(t('cmp_reason_mileage'));
    if (uniqMin(c => c.price > 0 ? c.price : null)) reasons.push(t('cmp_reason_cheaper'));
    if (uniqMax(c => c.power || null)) reasons.push(t('cmp_reason_power'));
    if (_driveScore(w.drive) === 2 && list.some(c => _driveScore(c.drive) === 1)) reasons.push(t('cmp_reason_awd'));
    if (w.customs === true && list.some(c => c.customs === false)) reasons.push(t('cmp_reason_customs'));
    const tail = reasons.length ? ' - ' + reasons.join(', ') : '';
    const price = w.price > 0 ? ` · $${w.price.toLocaleString()}` : '';
    return `<strong>${escapeHtml(w.title)}${price}</strong> ${t('cmp_better_pick')}${tail}`;
}

function renderCompareModal() {
    const list = getCompare();
    const modal = document.getElementById('cmp-modal');
    if (!modal || !list.length) return;
    const en = getLang() === 'en';
    const dash = '-';
    const multi = list.length > 1;
    const rows = [{
            label: t('filter_year'),
            disp: c => c.year || dash,
            val: c => c.year || null,
            better: 'high'
        },
        {
            label: t('spec_mileage'),
            disp: c => c.mileage ? c.mileage.toLocaleString() + (en ? ' km' : ' კმ') : dash,
            val: c => c.mileage || null,
            better: 'low'
        },
        {
            label: t('filter_price'),
            disp: c => c.price > 0 ? '$' + c.price.toLocaleString() : t('price_negotiable'),
            val: c => c.price > 0 ? c.price : null,
            better: 'low'
        },
        {
            label: t('spec_engine'),
            disp: c => c.engine ? c.engine + ' L' : dash
        },
        {
            label: t('spec_power'),
            disp: c => c.power ? c.power + (en ? ' hp' : ' ც.ძ.') : dash,
            val: c => c.power || null,
            better: 'high'
        },
        {
            label: t('filter_fuel'),
            disp: c => c.fuel ? escapeHtml(tval(c.fuel)) : dash
        },
        {
            label: t('filter_gearbox'),
            disp: c => c.gearbox ? escapeHtml(tval(c.gearbox)) : dash
        },
        {
            label: t('filter_drive'),
            disp: c => c.drive ? escapeHtml(tval(c.drive)) : dash,
            val: c => c.drive ? _driveScore(c.drive) : null,
            better: 'high'
        },
        {
            label: t('filter_body'),
            disp: c => c.body ? escapeHtml(tval(c.body)) : dash
        },
        {
            label: t('spec_customs'),
            disp: c => c.customs === true ? t('cleared') : c.customs === false ? t('not_cleared') : dash,
            val: c => c.customs === true ? 1 : c.customs === false ? 0 : null,
            better: 'high'
        },
        {
            label: t('filter_location'),
            disp: c => c.location ? escapeHtml(locLabel(c.location)) : dash
        },
    ];
    const wins = list.map(() => 0);
    const scoreRow = (row) => {
        if (!row.val || !multi) return list.map(() => '');
        const vals = list.map(row.val);
        const present = vals.filter(v => v != null);
        if (present.length < 2) return list.map(() => '');
        const best = row.better === 'high' ? Math.max(...present) : Math.min(...present);
        const worst = row.better === 'high' ? Math.min(...present) : Math.max(...present);
        if (best === worst) return list.map(() => '');
        return vals.map((v, ci) => {
            if (v == null) return '';
            if (v === best) {
                wins[ci]++;
                return 'cmp-best';
            }
            if (v === worst) return 'cmp-worst';
            return '';
        });
    };
    const rowCells = rows.map(scoreRow); // tallies `wins` as a side effect
    const scores = multi ? _cmpScores(list) : list.map(() => 0);
    const topScore = Math.max(...scores);
    const sorted = [...scores].sort((a, b) => b - a);
    const decisive = multi && topScore > 0 && (topScore - (sorted[1] || 0)) >= 0.4;
    const winnerIdx = decisive ? scores.indexOf(topScore) : -1;
    // count only metrics that actually produced a winner (both cars present, not a tie)
    const scored = rowCells.filter(cells => cells.some(c => c === 'cmp-best')).length;
    const head = list.map((c, ci) =>
        `<th class="${ci === winnerIdx ? 'cmp-winner' : ''}">` +
        (ci === winnerIdx ? `<div class="cmp-crown"><span>★</span> ${t('cmp_best_overall')}</div>` : '') +
        `<button class="cmp-remove" onclick="removeFromCompare('${escapeHtml(c.key)}')" title="${escapeHtml(t('remove'))}" aria-label="${escapeHtml(t('remove'))}"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 7h16M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2M6 7l1 13a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1l1-13M10 11v6M14 11v6"/></svg></button>` +
        `<a href="${escapeHtml(c.url)}" onclick="return goToCarDetail('${escapeHtml(c.key)}', event)">${_cmpImg(c.thumb, 'cmp-car-img')}</a>` +
        `<div class="cmp-car-title">${escapeHtml(c.title)}</div>` +
        `<div class="cmp-car-price">${c.price > 0 ? '$' + c.price.toLocaleString() : t('price_negotiable')}</div>` +
        (multi ? `<div class="cmp-wins"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M8 21h8M12 17v4M7 4h10v4a5 5 0 0 1-10 0zM7 5H4v2a3 3 0 0 0 3 3M17 5h3v2a3 3 0 0 1-3 3"/></svg>${t('cmp_leads_in', { n: wins[ci], m: scored })}</div>` : '') +
        `</th>`
    ).join('');
    const body = rows.map((row, ri) =>
        `<tr><td class="cmp-rowlabel">${row.label}</td>${list.map((c, ci) => {
            const cls = [rowCells[ri][ci], ci === winnerIdx ? 'cmp-wincol' : ''].filter(Boolean).join(' ');
            return `<td class="${cls}">${row.disp(c)}</td>`;
        }).join('')}</tr>`
    ).join('');
    const summary = multi ? _compareSummary(list, scores) : '';
    modal.querySelector('.cmp-body').innerHTML =
        (summary ? `<div class="cmp-summary">${summary}</div>` : '') +
        `<table class="cmp-table"><thead><tr><td class="cmp-rowlabel"></td>${head}</tr></thead><tbody>${body}</tbody></table>`;
    _syncCmpSaveBtn();
}
let _cmpOpener = null;

function _cmpFocusables(modal) {
    return [...modal.querySelectorAll('a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])')]
        .filter(el => el.offsetParent !== null);
}
window.openCompare = function() {
    let modal = document.getElementById('cmp-modal');
    if (!modal) {
        modal = document.createElement('div');
        modal.id = 'cmp-modal';
        modal.className = 'cmp-modal';
        modal.setAttribute('role', 'dialog');
        modal.setAttribute('aria-modal', 'true');
        modal.setAttribute('aria-labelledby', 'cmp-title');
        modal.innerHTML = `<div class="cmp-sheet"><div class="cmp-sheet-head"><h3 id="cmp-title">${escapeHtml(t('compare_title'))}</h3><div class="cmp-head-acts"><button class="cmp-save-btn" onclick="saveComparison()">♥ ${escapeHtml(t('save_comparison'))}</button><button class="cmp-x" onclick="closeCompare()" aria-label="close">✕</button></div></div><div class="cmp-body"></div></div>`;
        modal.addEventListener('click', (e) => {
            if (e.target === modal) closeCompare();
        });
        modal.addEventListener('keydown', (e) => {
            if (e.key !== 'Tab') return;
            const f = _cmpFocusables(modal);
            if (!f.length) return;
            const first = f[0],
                last = f[f.length - 1];
            if (e.shiftKey && document.activeElement === first) {
                e.preventDefault();
                last.focus();
            } else if (!e.shiftKey && document.activeElement === last) {
                e.preventDefault();
                first.focus();
            }
        });
        document.body.appendChild(modal);
    } else {
        modal.querySelector('h3').textContent = t('compare_title');
    }
    renderCompareModal();
    modal.classList.add('show');
    lockScroll('cmp');
    _cmpOpener = document.activeElement;
    const x = modal.querySelector('.cmp-x');
    if (x) x.focus();
};
window.closeCompare = function() {
    const modal = document.getElementById('cmp-modal');
    if (modal) modal.classList.remove('show');
    unlockScroll('cmp');
    if (_cmpOpener && typeof _cmpOpener.focus === 'function') {
        _cmpOpener.focus();
    }
    _cmpOpener = null;
};
window._refreshCompareUI = function() {
    renderCompareBar();
    const modal = document.getElementById('cmp-modal');
    if (modal && modal.classList.contains('show')) {
        modal.querySelector('h3').textContent = t('compare_title');
        renderCompareModal();
    }
};

function renderResults(data) {
    const meta = document.getElementById('search-meta');
    const results = document.getElementById('results');
    _lastCount = data.total_count;
    updateSearchBtnCount();

    for (const k in _slidesByCard) delete _slidesByCard[k];
    const _hidden = getHidden();
    const visible = data.results.filter(car => !_hidden.has(`${car.source}-${car.source_id}`));

    let metaText = `<strong class="text-ink">${t('results_count', { n: data.total_count })}</strong>`;
    if (data.remaining_searches != null) {
        metaText += ` <span class="text-muted">· ${t('results_remaining', { n: data.remaining_searches })}</span>`;
    }
    if (visible.length) {
        metaText += ` <button class="hist-chip" style="margin-left:10px;padding:4px 11px;font-size:12px" onclick="saveCurrentSearch(this)">♥ ${t('save_search')}</button>`;
    }
    meta.innerHTML = metaText;

    if (visible.length === 0) {
        results.innerHTML = `<div class="py-16 text-center text-muted">${t('no_results')}</div>`;
        return;
    }

    results.innerHTML = visible.map((car, i) => {
        const cardId = `c${i}`;
        const title = carTitle(car);
        const slides = buildSlides(car);
        _slidesByCard[cardId] = slides;
        const carKey = `${car.source}-${car.source_id}`;
        _carData[carKey] = {
            key: carKey,
            title,
            price: car.price_amount,
            currency: car.price_currency,
            thumb: (car.image_urls && car.image_urls[0]) || ''
        };
        _carFull[carKey] = car;

        const customsBadge = customsBadgeHtml(car);
        const cardVin = car.vin || vinFromText(car.description);
        const cardPhone = car.phone || phoneFromText(car.description);
        const contactLine = (cardVin || cardPhone) ?
            `<div class="rcard-contact">${cardVin ? `<span class="rc-vin">VIN ${escapeHtml(cardVin)}</span>` : ''}${cardPhone ? `<a class="rc-phone" href="tel:${escapeHtml(cardPhone.replace(/\s/g, ''))}" onclick="event.stopPropagation()">☎ ${escapeHtml(cardPhone)}</a>` : ''}</div>` :
            '';
        return `
            <article class="rcard" style="animation-delay:${Math.min(i, 8) * 45}ms">
              <div class="rcard-photo">${photoBlockHtml(cardId, slides)}</div>
              <div class="rcard-body">
                <div class="rcard-top">
                  <div class="min-w-0">
                    <a class="rcard-title" href="/car/${escapeHtml(carKey)}"
                       onclick="return goToCarDetail('${escapeHtml(carKey)}', event)">${escapeHtml(title)}</a>
                    ${car.location ? `<div class="rcard-loc">${escapeHtml(locLabel(car.location))}</div>` : ''}
                  </div>
                  <div class="rcard-acts">
                    <button class="rcard-compare ${isInCompare(carKey) ? 'on' : ''}" data-key="${escapeHtml(carKey)}" aria-pressed="${isInCompare(carKey) ? 'true' : 'false'}" onclick="event.stopPropagation(); toggleCompare('${escapeHtml(carKey)}', this)" title="${t('act_compare')}" aria-label="${t('act_compare')}">${ICON_COMPARE}</button>
                    <button class="rcard-hide" onclick="event.stopPropagation(); hideCar('${escapeHtml(carKey)}', this)" title="${t('act_hide')}" aria-label="${t('act_hide')}">${ICON_HIDE}</button>
                    <button class="save-btn ${isCarSaved(carKey) ? 'is-saved' : ''}" data-key="${escapeHtml(carKey)}" aria-pressed="${isCarSaved(carKey) ? 'true' : 'false'}" onclick="event.stopPropagation(); toggleSave('${escapeHtml(carKey)}', this)" aria-label="save">${ICON_HEART}</button>
                  </div>
                </div>
                <div class="rcard-specs">${carSpecPills(car)}</div>
                ${contactLine}
                <div class="rcard-bot">
                  <div class="rcard-price${car.price_amount > 0 ? '' : ' negotiable'}">${car.price_amount > 0 ? '$' + car.price_amount.toLocaleString() : t('price_negotiable')}</div>
                  <div class="rcard-badges">${customsBadge}${sourceBadgeHtml(car)}</div>
                </div>
              </div>
            </article>`;
    }).join('') + paginationHtml(data);
}

function buildSlides(car) {
    const slides = [];
    const ytId = youtubeId(car.video_url);
    if (ytId) {
        slides.push({
            type: 'video',
            src: `https://www.youtube.com/embed/${ytId}`
        });
    }
    if (car.image_urls && car.image_urls.length) {
        for (const url of car.image_urls) slides.push({
            type: 'image',
            src: url
        });
    }
    return slides;
}

function descriptionHtml(desc) {
    if (!desc) return '';
    const long = desc.length > 180 || (desc.match(/\n/g) || []).length > 4;
    return `
        <div class="desc-block">
          <div class="desc-head">
            <span class="spec-label">${t('section_description')}</span>
            <button class="desc-translate" onclick="translateDesc(this)" title="${t('translate_btn')}">
              <svg class="tr-ic" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 5h7"/><path d="M9 3v2c0 4.418 -2.239 8 -5 8"/><path d="M5 9c0 2.144 2.952 3.908 6.7 4"/><path d="M11.5 21l4.5 -11l4.5 11"/><path d="M14.5 17.5l4.5 0"/></svg>
              <span>${t('translate_btn')}</span>
            </button>
          </div>
          <div class="description${long ? ' clamped' : ''}">${escapeHtml(desc)}</div>
          ${long ? `<button class="see-more" onclick="toggleDesc(this)">${t('see_more')}</button>` : ''}
          <div class="tr-pop" hidden></div>
        </div>`;
}

const _TR_LANGS = [
    ['en', 'English'],
    ['ru', 'Русский'],
    ['kk', 'Қазақша']
];
window.translateDesc = function(btn) {
    const block = btn.closest('.desc-block');
    const pop = block.querySelector('.tr-pop');
    if (!pop.hidden) {
        pop.hidden = true;
        btn.classList.remove('is-on');
        return;
    }
    btn.classList.add('is-on');
    pop.hidden = false;
    pop.innerHTML =
        `<div class="tr-pop-head">
           <div class="tr-langs">${_TR_LANGS.map((l, i) => `<button class="tr-lang${i === 0 ? ' on' : ''}" data-tl="${l[0]}">${l[1]}</button>`).join('')}</div>
           <button class="tr-pop-x" onclick="this.closest('.tr-pop').hidden=true" aria-label="close">✕</button>
         </div>
         <div class="tr-pop-body" id="tr-body"></div>`;
    pop.querySelectorAll('.tr-lang').forEach((b) => b.onclick = () => {
        pop.querySelectorAll('.tr-lang').forEach((x) => x.classList.toggle('on', x === b));
        doTranslate(block, b.dataset.tl);
    });
    doTranslate(block, 'en');
};

async function doTranslate(block, tl) {
    const box = block.querySelector('.description');
    const body = block.querySelector('.tr-pop-body');
    const text = (box.textContent || '').trim();
    if (!text || !body) return;
    body.innerHTML = `<span class="tr-pop-load">${t('translating')}…</span>`;
    try {
        const url = `https://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl=${tl}&dt=t&q=${encodeURIComponent(text)}`;
        const resp = await fetch(url);
        const data = await resp.json();
        const out = (data[0] || []).map((s) => s[0]).join('');
        body.textContent = out || t('err_unknown');
    } catch (e) {
        body.textContent = t('err_unknown');
    }
}

window.toggleDesc = function(btn) {
    const desc = btn.parentElement.querySelector('.description');
    clearTimeout(desc._animT);
    desc.style.transition = desc.style.height = desc.style.overflow = '';
    const from = desc.offsetHeight;
    const clamped = desc.classList.toggle('clamped');
    const to = desc.offsetHeight;
    btn.textContent = t(clamped ? 'see_more' : 'see_less');
    if (from === to || matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    // line-clamp hides the extra lines even mid-transition, so release it while
    desc.classList.remove('clamped');
    desc.style.height = from + 'px';
    desc.style.overflow = 'hidden';
    void desc.offsetHeight;
    desc.style.transition = 'height .28s ease';
    desc.style.height = to + 'px';
    desc._animT = setTimeout(() => {
        desc.style.transition = desc.style.height = desc.style.overflow = '';
        if (clamped) desc.classList.add('clamped');
    }, 300);
};

const _CAR_KEY_RE = /^\/car\/((?:autopapa|myauto)-\d+)\/?$/;

function parseRoute(path) {
    path = path || location.pathname;
    if (path === '/' || path === '') return {
        view: 'search'
    };
    const m = path.match(_CAR_KEY_RE);
    return m ? {
        view: 'detail',
        key: m[1]
    } : {
        view: 'notfound'
    };
}

function showNotFound() {
    document.body.classList.add('mode-detail');
    document.body.classList.remove('mode-results');
    document.getElementById('empty-state').classList.add('hidden');
    document.getElementById('results').innerHTML = `
        <div class="notfound">
          <div class="notfound-code">404</div>
          <p class="notfound-msg">${t('notfound_msg')}</p>
          <a href="/" class="detail-btn" onclick="return goToSearch(event)">${t('notfound_home')}</a>
        </div>`;
}

function showSearchView() {
    document.body.classList.remove('mode-detail');
    if (lastResponse) {
        document.body.classList.remove('mode-detail');
        document.body.classList.add('mode-results');
        document.getElementById('empty-state').classList.add('hidden');
        renderResults(lastResponse);
    } else {
        document.body.classList.remove('mode-results');
        document.getElementById('results').innerHTML = '';
        document.getElementById('empty-state').classList.remove('hidden');
    }
}

function showDetailView(key) {
    document.body.classList.add('mode-detail');
    document.getElementById('empty-state').classList.add('hidden');
    document.getElementById('results').innerHTML =
        `<div class="py-16 text-center text-muted">${t('detail_loading')}</div>`;
    fetchCarDetail(key);
}

async function fetchCarDetail(key) {
    const results = document.getElementById('results');
    try {
        const resp = await fetch(`${API_BASE}/car/${key}`);
        if (resp.status === 404) {
            showNotFound();
            return;
        }
        if (!resp.ok) throw new Error('HTTP ' + resp.status);
        const car = await resp.json();
        renderDetail(car);
    } catch (e) {
        results.innerHTML = `<div class="py-16 text-center text-accent">${t('err_fetch', { msg: e.message })}</div>`;
    }
}

let _detailSlides = [];
let _detailCar = null;

let _detailMainIdx = 0;

function renderDetail(car) {
    _detailCar = car;
    _detailMainIdx = 0;
    pushViewed(car);
    const title = carTitle(car);
    const slides = buildSlides(car);
    _detailSlides = slides;
    const km = getLang() === 'en' ? ' km' : ' კმ';

    const mainSrc = (s) => s && s.type === 'image' ? s.src : (s ? thumbSrc(s) : '');
    const gallery = slides.length ? `
        <div class="dt-gallery">
          <button class="dt-main" id="dt-main-btn" onclick="openDetailLightbox(0)">
            <img id="dt-main-img" src="${escapeHtml(mainSrc(slides[0]))}" alt="" decoding="async" onerror="_photoFail(this)">
            ${slides.length > 1 ? `<span class="dt-count">${t('photo_counter', { i: 1, n: slides.length })}</span>
            <span class="ph-nav ph-prev" onclick="event.stopPropagation(); dtSlideBy(-1)" role="button" aria-label="prev">‹</span>
            <span class="ph-nav ph-next" onclick="event.stopPropagation(); dtSlideBy(1)" role="button" aria-label="next">›</span>` : ''}
          </button>
          ${slides.length > 1 ? `<div class="dt-thumbs">${slides.slice(0, 14).map((s, i) =>
              `<button class="dt-thumb ${i === 0 ? 'on' : ''}" onclick="dtSetMain(${i})"><img src="${escapeHtml(thumbSrc(s))}" alt="" loading="lazy" onerror="_photoFail(this)"></button>`).join('')}</div>` : ''}
        </div>` : `<div class="dt-gallery"><div class="no-photo" style="aspect-ratio:4/3;border-radius:14px">${t('no_photos')}</div></div>`;

    const en = getLang() === 'en';
    const hl = [];
    if (car.body_type) hl.push([_bodyIcon(car.body_type), tval(car.body_type), t('filter_body')]);
    if (car.year) hl.push([_PIC(_FILTER_ICONS.year), car.year, t('spec_year')]);
    if (car.mileage_km) hl.push([_mileageGauge(car.mileage_km), car.mileage_km.toLocaleString() + km, t('spec_mileage')]);
    if (car.engine_volume_l) hl.push([_PILL_IC.engine, car.engine_volume_l + ' L', t('spec_engine')]);
    if (car.power_hp) hl.push([_PILL_IC.bolt, car.power_hp + (en ? ' hp' : ' ც.ძ.'), t('spec_power')]);
    if (car.engine_type) hl.push([_fuelIcon(car.engine_type), tval(car.engine_type), t('spec_fuel')]);
    if (car.gearbox) hl.push([_gearIcon(car.gearbox), tval(car.gearbox), t('spec_gearbox')]);
    if (car.drive_wheels) hl.push([_driveIcon(car.drive_wheels), tval(car.drive_wheels), t('spec_drive')]);
    const hlGrid = hl.length ? `<div class="dt-hl">${hl.map(([ic, v, l]) => `<div class="dt-hl-tile">${ic}<div class="dt-hl-v">${escapeHtml(String(v))}</div><div class="dt-hl-l">${escapeHtml(l)}</div></div>`).join('')}</div>` : '';

    const srow = (k, v) => `<div class="dt-srow"><span class="k">${k}</span><span class="v">${escapeHtml(String(v))}</span></div>`;
    const specs = [];
    if (car.color) specs.push(srow(t('spec_color'), tval(car.color)));
    if (car.steering) specs.push(srow(t('spec_steering'), tval(car.steering)));

    const phones = splitPhones(car.phone || '');
    const calls = phones.length ?
        phones.map(p => `<a class="dt-call" href="tel:${escapeHtml(p.replace(/\s/g, ''))}">☎ ${escapeHtml(p)}</a>`).join('') :
        '';
    const customs = customsBadgeHtml(car);
    const priceMissing = !(car.price_amount > 0);
    const price = priceMissing ? t('price_negotiable') : '$' + car.price_amount.toLocaleString();
    const dateLine = car.posted_date && car.posted_date.trim() ?
        t('posted_on', {
            date: escapeHtml(car.posted_date.trim())
        }) :
        t('scraped_on_note', {
            date: formatDate(car.created_at)
        });
    const carKey = `${car.source}-${car.source_id}`;
    _carData[carKey] = {
        key: carKey,
        title,
        price: car.price_amount,
        currency: car.price_currency,
        thumb: (car.image_urls && car.image_urls[0]) || ''
    };
    _carFull[carKey] = car;
    const saved = isCarSaved(carKey);
    // VIN gets its own prominent, shimmering card - sellers and buyers look for it first
    const detailVin = car.vin || vinFromText(car.description) || '';
    const vinCard = detailVin ?
        `<div class="dt-vin-card"><span class="dt-vin-badge">VIN</span><span class="dt-vin-code mono">${escapeHtml(detailVin)}</span><button class="dt-vin-copy" data-copy="${escapeHtml(detailVin)}" onclick="copyText(this)" title="${escapeHtml(t('copy_vin'))}" aria-label="${escapeHtml(t('copy_vin'))}">${ICON_COPY}</button></div>` :
        '';
    const contact = [
        car.seller_name ? `<div class="dt-cline"><span class="dt-clabel">${t('section_seller')}</span><span class="dt-cval">${escapeHtml(car.seller_name)}</span></div>` : '',
    ].filter(Boolean).join('');

    document.getElementById('results').innerHTML = `
        <div class="dt-bar">
          <a href="/" class="detail-btn" onclick="return goToSearch(event)">${t('back_to_search')}</a>
          <div class="dt-actions">
            <button class="rcard-compare dt-compare ${isInCompare(carKey) ? 'on' : ''}" data-key="${escapeHtml(carKey)}" aria-pressed="${isInCompare(carKey) ? 'true' : 'false'}" onclick="toggleCompare('${escapeHtml(carKey)}', this)" title="${t('act_compare')}" aria-label="${t('act_compare')}">${ICON_COMPARE}</button>
            <button class="save-btn dt-fav ${saved ? 'is-saved' : ''}" data-key="${escapeHtml(carKey)}" aria-pressed="${saved ? 'true' : 'false'}" onclick="toggleSave('${escapeHtml(carKey)}', this)" aria-label="save">${ICON_HEART}</button>
            <button class="detail-btn detail-icon-btn" onclick="copyDetailLink(this)" title="${t('copy_link')}" aria-label="${t('copy_link')}">${ICON_COPY}</button>
          </div>
        </div>
        <div class="dt-grid">
          ${gallery}
          <div class="dt-panel">
            <div class="dt-ptop">
              <div class="min-w-0">
                <h1 class="dt-title">${escapeHtml(title)}</h1>
                ${car.location ? `<p class="dt-loc">${escapeHtml(locLabel(car.location))}</p>` : ''}
              </div>
              ${sourceBadgeHtml(car)}
            </div>
            ${hlGrid}
            <div class="dt-pricebox"><span class="dt-price${priceMissing ? ' negotiable' : ''}">${price}</span>${customs}</div>
            ${vinCard}
            ${specs.length ? `<div class="dt-specs">${specs.join('')}</div>` : ''}
            ${calls ? `<div class="dt-calls">${calls}</div>` : ''}
            ${contact ? `<div class="dt-contact">${contact}</div>` : ''}
            ${car.url && /^https?:\/\//i.test(car.url) ? `<a href="${escapeHtml(car.url)}" target="_blank" rel="noopener" class="dt-source">${t('detail_open_source')} ↗</a>` : ''}
          </div>
        </div>
        ${car.description ? `<div class="dt-desc">${descriptionHtml(car.description)}</div>` : ''}
        <div class="dt-meta">${dateLine}</div>`;
    if (_detailSlides.length > 1) {
        addSwipe(document.getElementById('dt-main-btn'),
            () => dtSetMain(Math.min(_detailMainIdx + 1, _detailSlides.length - 1)),
            () => dtSetMain(Math.max(_detailMainIdx - 1, 0)));
    }
}

window.dtSetMain = function(i) {
    const s = _detailSlides[i];
    if (!s) return;
    _detailMainIdx = i;
    const img = document.getElementById('dt-main-img');
    if (img) {
        img.src = s.type === 'image' ? s.src : thumbSrc(s);
        img.classList.remove('photo-anim');
        void img.offsetWidth;
        img.classList.add('photo-anim'); // animate switch
    }
    const btn = document.getElementById('dt-main-btn');
    if (btn) btn.setAttribute('onclick', `openDetailLightbox(${i})`);
    const c = document.querySelector('.dt-count');
    if (c) c.textContent = t('photo_counter', {
        i: i + 1,
        n: _detailSlides.length
    });
    document.querySelectorAll('.dt-thumb').forEach((el, j) => el.classList.toggle('on', j === i));
};

window.dtSlideBy = function(delta) {
    if (_detailSlides.length < 2) return;
    let i = _detailMainIdx + delta;
    if (i < 0) i = _detailSlides.length - 1;
    if (i >= _detailSlides.length) i = 0;
    dtSetMain(i);
};

window.openDetailLightbox = function(idx) {
    if (_detailSlides.length) openLightbox(_detailSlides, idx);
};

let _searchScrollY = 0;

window.goToCarDetail = function(key, ev) {
    if (ev) ev.preventDefault();
    const cm = document.getElementById('cmp-modal');
    if (cm && cm.classList.contains('show')) closeCompare();
    if (document.querySelector('#saved-drawer.open')) closeSaved();
    if (_lightbox) closeLightbox();
    _searchScrollY = window.scrollY;
    history.pushState({
        view: 'detail',
        key
    }, '', `/car/${key}`);
    showDetailView(key);
    window.scrollTo(0, 0);
    return false;
};

window.goToSearch = function(ev) {
    if (ev) ev.preventDefault();
    history.pushState({
        view: 'search'
    }, '', '/');
    showSearchView();
    if (lastResponse && _lastPayload) _syncUrl(_lastPayload); // keep the shareable link
    requestAnimationFrame(() => window.scrollTo(0, _searchScrollY));
    return false;
};

const ICON_COPY = '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h8"/></svg>';
const ICON_CHECK = '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12l4 4 10-10"/></svg>';

function _copyFeedback(btn) {
    const orig = btn.innerHTML;
    btn.innerHTML = ICON_CHECK;
    btn.classList.add('is-copied');
    setTimeout(() => {
        btn.innerHTML = orig;
        btn.classList.remove('is-copied');
    }, 1300);
}

window.copyDetailLink = function(btn) {
    const url = location.href;
    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(url).then(() => _copyFeedback(btn)).catch(() => window.prompt('', url));
    } else {
        window.prompt('', url);
    }
};

window.copyText = function(arg, maybeBtn) {
    let text, btn;
    if (arg && arg.nodeType === 1) {
        btn = arg;
        text = arg.getAttribute('data-copy') || '';
    } else {
        text = arg;
        btn = maybeBtn;
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(() => _copyFeedback(btn)).catch(() => window.prompt('', text));
    } else {
        window.prompt('', text);
    }
};

window.quickSearch = function(q) {
    const el = document.getElementById('search-input');
    if (el) el.value = q;
    doSearch();
    el.scrollIntoView({
        behavior: 'smooth',
        block: 'center'
    });
};

(function loadHeroCount() {
    fetch(API_BASE + '/stats')
        .then((r) => (r.ok ? r.json() : null))
        .then((d) => {
            if (!d || typeof d.total_cars !== 'number') return;
            const el = document.getElementById('hero-count');
            if (el) el.textContent = d.total_cars.toLocaleString() + '+';
        })
        .catch(() => {});
})();

const _carData = {};
const LS_CARS = 'cdb_saved',
    LS_SEARCHES = 'cdb_searches',
    LS_HIST = 'cdb_history',
    LS_VIEWED = 'cdb_viewed';

function lsGet(k) {
    try {
        const v = JSON.parse(localStorage.getItem(k));
        return Array.isArray(v) ? v : [];
    } catch (_) {
        return [];
    }
}

function lsSet(k, v) {
    try {
        localStorage.setItem(k, JSON.stringify(v));
    } catch (_) {}
}

function pushViewed(car) {
    const item = {
        key: `${car.source}-${car.source_id}`,
        title: carTitle(car),
        price: car.price_amount,
        currency: car.price_currency,
        thumb: (car.image_urls && car.image_urls[0]) || '',
    };
    let v = lsGet(LS_VIEWED).filter((x) => x.key !== item.key);
    v.unshift(item);
    lsSet(LS_VIEWED, v.slice(0, 40));
}
window.clearViewed = function() {
    lsSet(LS_VIEWED, []);
    renderSaved();
};

function getSavedCars() {
    return lsGet(LS_CARS);
}

function isCarSaved(key) {
    return getSavedCars().some(c => c.key === key);
}
window.toggleSave = function(key, btn) {
    let cars = getSavedCars();
    const had = cars.some(c => c.key === key);
    cars = had ? cars.filter(c => c.key !== key) : [(_carData[key] || {
        key: key,
        title: key
    }), ...cars].slice(0, 300);
    lsSet(LS_CARS, cars);
    if (btn && !had) {
        btn.classList.remove('pop');
        void btn.offsetWidth;
        btn.classList.add('pop');
    }
    refreshHearts();
    updateSavedCount();
};

function refreshHearts() {
    document.querySelectorAll('.save-btn[data-key]').forEach((b) => {
        const s = isCarSaved(b.dataset.key);
        b.classList.toggle('is-saved', s);
        b.setAttribute('aria-pressed', s ? 'true' : 'false');
    });
}

function describeSearch(p) {
    const en = getLang() === 'en';
    const parts = [];
    if (p.query) parts.push(p.query);
    if (p.manufacturers && p.manufacturers.length) parts.push(p.manufacturers.join(', '));
    if (p.models && p.models.length) parts.push(p.models.join(', '));
    if (p.year_from || p.year_to) parts.push((p.year_from || '…') + '-' + (p.year_to || '…'));
    if (p.price_from || p.price_to) parts.push('$' + (p.price_from || '0') + '-' + (p.price_to || '∞'));
    if (p.mileage_from || p.mileage_to) parts.push((p.mileage_from || '0') + '-' + (p.mileage_to || '∞') + (en ? ' km' : ' კმ'));
    (p.body_types || []).forEach(v => parts.push(tval(v)));
    (p.fuels || []).forEach(v => parts.push(tval(v)));
    (p.gearboxes || []).forEach(v => parts.push(tval(v)));
    (p.drives || []).forEach(v => parts.push(tval(v)));
    [...new Set((p.locations || []).map(locLabel))].forEach(v => parts.push(v));
    if (p.customs_cleared === true) parts.push(t('cleared'));
    if (p.customs_cleared === false) parts.push(t('not_cleared'));
    if (p.sort) parts.push(t('sort_' + p.sort));
    return parts.join(' · ') || t('save_search');
}

function _searchParts(p) {
    const en = getLang() === 'en';
    const out = [];
    if (p.query) out.push({
        label: t('q_label'),
        value: p.query
    });
    if (p.manufacturers && p.manufacturers.length) out.push({
        label: t('filter_brand'),
        value: p.manufacturers.join(', ')
    });
    if (p.models && p.models.length) out.push({
        label: t('filter_model'),
        value: p.models.join(', ')
    });
    if (p.year_from || p.year_to) out.push({
        label: t('filter_year'),
        value: (p.year_from || '…') + '-' + (p.year_to || '…')
    });
    if (p.price_from || p.price_to) out.push({
        label: t('filter_price'),
        value: '$' + (p.price_from || '0') + '-' + (p.price_to || '∞')
    });
    if (p.mileage_from || p.mileage_to) out.push({
        label: t('spec_mileage'),
        value: (p.mileage_from || '0') + '-' + (p.mileage_to || '∞') + (en ? ' km' : ' კმ')
    });
    if (p.body_types && p.body_types.length) out.push({
        label: t('filter_body'),
        value: p.body_types.map(tval).join(', ')
    });
    if (p.fuels && p.fuels.length) out.push({
        label: t('filter_fuel'),
        value: p.fuels.map(tval).join(', ')
    });
    if (p.gearboxes && p.gearboxes.length) out.push({
        label: t('filter_gearbox'),
        value: p.gearboxes.map(tval).join(', ')
    });
    if (p.drives && p.drives.length) out.push({
        label: t('filter_drive'),
        value: p.drives.map(tval).join(', ')
    });
    if (p.locations && p.locations.length) out.push({
        label: t('filter_location'),
        value: [...new Set(p.locations.map(locLabel))].join(', ')
    });
    if (p.customs_cleared === true) out.push({
        label: t('spec_customs'),
        value: t('cleared')
    });
    if (p.customs_cleared === false) out.push({
        label: t('spec_customs'),
        value: t('not_cleared')
    });
    if (p.sort) out.push({
        label: t('filter_sort'),
        value: t('sort_' + p.sort)
    });
    return out;
}

function _payloadOf(item) {
    return (item && item.payload) || (item && item.q != null ? {
        query: item.q,
        sort: item.sort
    } : (typeof item === 'string' ? {
        query: item
    } : {}));
}

function _chipShort(item) {
    const parts = _searchParts(_payloadOf(item));
    if (!parts.length) return {
        text: (item && item.label) || t('save_search'),
        extra: 0
    };
    return {
        text: parts[0].value,
        extra: parts.length - 1
    };
}

function _detailHtml(item) {
    const parts = _searchParts(_payloadOf(item));
    if (!parts.length) return `<div class="sd-row"><span class="sd-val">${escapeHtml(t('save_search'))}</span></div>`;
    return parts.map(pt => `<div class="sd-row"><span class="sd-label">${escapeHtml(pt.label)}</span><span class="sd-val">${escapeHtml(pt.value)}</span></div>`).join('');
}
const CHIP_CHEV = '<svg class="chip-chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg>';

function _chipBtnInner(item, saved) {
    const short = _chipShort(item);
    const badge = short.extra ? `<span class="chip-more-n">+${short.extra}</span>` : '';
    return (saved ? ICON_HEART : '') + `<span class="chip-text">${escapeHtml(short.text)}</span>` + badge;
}

function _searchChip(o) {
    const save = o.saveKind ? `<button class="chip-save" data-kind="${o.saveKind}" data-i="${o.i}" aria-label="${escapeHtml(t('save_search'))}" title="${escapeHtml(t('save_search'))}">♡</button>` : '';
    return `<span class="chip-wrap">` +
        `<button class="hist-chip ${o.saved ? 'pinned' : ''}" data-kind="${o.runKind}" data-i="${o.i}" title="${escapeHtml(_histLabel(o.item))}">${_chipBtnInner(o.item, o.saved)}</button>` +
        `<button class="chip-expand" data-exp="${o.uid}" aria-label="${escapeHtml(t('expand'))}" title="${escapeHtml(t('expand'))}">${CHIP_CHEV}</button>` +
        save +
        `<button class="chip-del" data-kind="${o.delKind}" data-i="${o.i}" aria-label="${escapeHtml(t('remove'))}">✕</button>` +
        `</span><div class="search-detail" id="${o.uid}" hidden>${_detailHtml(o.item)}</div>`;
}

function _wireChipExpand(scope) {
    scope.querySelectorAll('.chip-expand').forEach(b => {
        b.onclick = (e) => {
            e.stopPropagation();
            const d = document.getElementById(b.dataset.exp);
            if (!d) return;
            const show = d.hasAttribute('hidden');
            d.toggleAttribute('hidden', !show);
            b.classList.toggle('open', show);
        };
    });
}

window.saveCurrentSearch = function(btn) {
    const payload = buildSearchPayload();
    delete payload.page;
    if (Object.keys(payload).length === 0) return;
    const key = JSON.stringify(payload);
    let s = lsGet(LS_SEARCHES);
    const exists = s.some((x) => JSON.stringify(x.payload) === key);
    s = s.filter((x) => JSON.stringify(x.payload) !== key);
    if (exists) {
        if (btn) btn.textContent = '♡ ' + t('save_search');
    } else {
        s = [{
            payload: payload,
            label: describeSearch(payload)
        }, ...s];
        if (btn) btn.textContent = '♥ ' + t('saved_done');
    }
    lsSet(LS_SEARCHES, s.slice(0, 40));
    updateSavedCount();
    renderRecent();
};

function _setVal(id, v) {
    const el = document.getElementById(id);
    if (el) el.value = (v == null ? '' : v);
}

function _setMulti(id, values) {
    const sel = document.getElementById(id);
    if (!sel) return;
    // empty == "no filter" == all checked, to match the all-selected-by-default filters
    if (!values || !values.length) {
        Array.from(sel.options).forEach(o => {
            o.selected = !!o.value;
        });
        return;
    }
    const set = new Set(values);
    Array.from(sel.options).forEach(o => {
        o.selected = o.value ? o.value.split(_LOC_SEP).some(v => set.has(v)) : false;
    });
}

function applySearchPayload(p) {
    _setVal('search-input', p.query);
    _setVal('f-year-from', p.year_from);
    _setVal('f-year-to', p.year_to);
    _setVal('f-price-from', p.price_from);
    _setVal('f-price-to', p.price_to);
    _setVal('f-mileage-from', p.mileage_from);
    _setVal('f-mileage-to', p.mileage_to);
    _setMulti('f-brand', p.manufacturers);
    document.getElementById('f-brand').dispatchEvent(new Event('change', {
        bubbles: true
    })); // rebuild model options
    _setMulti('f-model', p.models);
    _setMulti('f-body', p.body_types);
    _setMulti('f-fuel', p.fuels);
    _setMulti('f-gearbox', p.gearboxes);
    _setMulti('f-drive', p.drives);
    _setMulti('f-location', p.locations);
    document.getElementById('f-customs').value = p.customs_cleared === true ? 'yes' : p.customs_cleared === false ? 'no' : '';
    _setVal('f-sort', p.sort);
    refreshDropdowns();
    updateFilterResets();
    document.getElementById('search-input').dispatchEvent(new Event('input'));
}
// running a saved search/history item from a car page must return to the search route,
// else doSearch's URL sync no-ops and the address bar stays stuck on /car/<key>
function _ensureSearchRoute() {
    if (parseRoute().view !== 'search') history.pushState({
        view: 'search'
    }, '', '/');
}

function runSavedSearch(item) {
    closeSaved();
    _ensureSearchRoute();
    applySearchPayload((item && item.payload) || (item && item.q != null ? {
        query: item.q,
        sort: item.sort
    } : {}));
    doSearch();
}

function runHistory(item) {
    if (item && item.payload) return runSavedSearch(item);
    const q = typeof item === 'string' ? item : '';
    closeSaved();
    _ensureSearchRoute();
    const el = document.getElementById('search-input');
    el.value = q;
    el.dispatchEvent(new Event('input'));
    doSearch();
}

function pushHistory() {
    const payload = buildSearchPayload();
    delete payload.page;
    if (Object.keys(payload).length === 0) return;
    const key = JSON.stringify(payload);
    const same = (x) => JSON.stringify((x && x.payload) || {
        query: x
    }) === key;
    let h = lsGet(LS_HIST).filter(x => !same(x));
    h.unshift({
        payload,
        label: describeSearch(payload)
    });
    lsSet(LS_HIST, h.slice(0, 12));
    renderRecent();
}

function _histLabel(item) {
    return (item && item.label) || (item && item.payload ? describeSearch(item.payload) : String(item || ''));
}

function _saveHistItem(i) {
    const item = lsGet(LS_HIST)[i];
    if (!item) return;
    const payload = (item && item.payload) || {
        query: String(item)
    };
    const key = JSON.stringify(payload);
    const s = lsGet(LS_SEARCHES);
    if (s.some(x => JSON.stringify(x.payload) === key)) return;
    lsSet(LS_SEARCHES, [{
        payload,
        label: describeSearch(payload)
    }, ...s].slice(0, 40));
    updateSavedCount();
    renderRecent();
}

let _recentAll = false;

function renderRecent() {
    const row = document.getElementById('recent-row');
    if (!row) return;
    const allSaved = lsGet(LS_SEARCHES),
        allHist = lsGet(LS_HIST);
    if (!allSaved.length && !allHist.length) {
        row.innerHTML = '';
        return;
    }
    const narrow = matchMedia('(max-width: 560px)').matches;
    const SCAP = narrow ? 2 : 4,
        HCAP = narrow ? 3 : 5;
    const saved = _recentAll ? allSaved : allSaved.slice(0, SCAP);
    const hist = _recentAll ? allHist : allHist.slice(0, HCAP);
    let html = '';
    if (saved.length) {
        html += `<span class="recent-label">${t('saved_searches_h')}</span>` +
            saved.map((s, i) => _searchChip({
                runKind: 'saved',
                delKind: 'saved-del',
                i,
                item: s,
                uid: 'sdr-s-' + i,
                saved: true
            })).join('');
    }
    if (hist.length) {
        html += `<span class="recent-label">${t('recent_h')}</span>` +
            hist.map((item, i) => _searchChip({
                runKind: 'hist',
                delKind: 'hist-del',
                saveKind: 'hist-save',
                i,
                item,
                uid: 'sdr-h-' + i,
                saved: false
            })).join('') +
            `<button class="hist-chip recent-clear" data-kind="clear-all">✕ ${t('clear_all')}</button>`;
    }
    const total = allSaved.length + allHist.length,
        shown = saved.length + hist.length;
    if (!_recentAll && total > shown) html += `<button class="hist-chip recent-toggle" data-kind="more">${t('load_more')} · ${total - shown}</button>`;
    else if (_recentAll && total > SCAP + HCAP) html += `<button class="hist-chip recent-toggle" data-kind="less">${t('show_less')}</button>`;
    row.innerHTML = html;
    row.querySelectorAll('.hist-chip[data-kind], .chip-del[data-kind], .chip-save[data-kind]').forEach((b) => {
        b.onclick = (e) => {
            e.stopPropagation();
            const i = +b.dataset.i;
            switch (b.dataset.kind) {
                case 'saved': {
                    const s = lsGet(LS_SEARCHES)[i];
                    if (s) runSavedSearch(s);
                    break;
                }
                case 'saved-del': {
                    const s = lsGet(LS_SEARCHES);
                    s.splice(i, 1);
                    lsSet(LS_SEARCHES, s);
                    updateSavedCount();
                    renderRecent();
                    break;
                }
                case 'hist': {
                    const item = lsGet(LS_HIST)[i];
                    if (item) runHistory(item);
                    break;
                }
                case 'hist-save':
                    _saveHistItem(i);
                    break;
                case 'hist-del': {
                    const h = lsGet(LS_HIST);
                    h.splice(i, 1);
                    lsSet(LS_HIST, h);
                    renderRecent();
                    break;
                }
                case 'clear-all':
                    lsSet(LS_HIST, []);
                    renderRecent();
                    break;
                case 'more':
                    _recentAll = true;
                    renderRecent();
                    break;
                case 'less':
                    _recentAll = false;
                    renderRecent();
                    break;
            }
        };
    });
    _wireChipExpand(row);
}
window.clearHistory = function() {
    lsSet(LS_HIST, []);
    renderSaved();
    renderRecent();
};
window.clearSavedCars = function() {
    lsSet(LS_CARS, []);
    updateSavedCount();
    renderSaved();
};
window.clearSavedSearches = function() {
    lsSet(LS_SEARCHES, []);
    updateSavedCount();
    renderSaved();
};

function updateSavedCount() {
    const el = document.getElementById('saved-count');
    if (!el) return;
    const n = getSavedCars().length + lsGet(LS_SEARCHES).length;
    el.textContent = n;
    const trig = el.closest('.saved-trigger');
    if (trig) trig.classList.toggle('has-items', n > 0);
}

const _DRAWER_PAGE = 8;
let _drawerShown = {};

function _loadMore(section, total, shown) {
    if (total <= shown) return '';
    return `<button class="drawer-more" data-more="${section}">${t('load_more')} · ${total - shown}</button>`;
}
window.drawerShowMore = function(section) {
    _drawerShown[section] = (_drawerShown[section] || _DRAWER_PAGE) + _DRAWER_PAGE;
    renderSaved();
};

let _savedOpener = null;
window.openSaved = function() {
    _savedOpener = document.activeElement;
    _drawerShown = {};
    renderSaved();
    document.getElementById('saved-overlay').classList.add('open');
    document.getElementById('saved-drawer').classList.add('open');
    document.body.classList.add('saved-open');
    lockScroll('saved');
};
window.closeSaved = function() {
    document.getElementById('saved-overlay').classList.remove('open');
    document.getElementById('saved-drawer').classList.remove('open');
    document.body.classList.remove('saved-open');
    unlockScroll('saved');
    if (_savedOpener && typeof _savedOpener.focus === 'function') _savedOpener.focus({
        preventScroll: true
    });
    _savedOpener = null;
};

const EXPORT_KEYS = [LS_CARS, LS_SEARCHES, LS_HIST, LS_VIEWED, HIDDEN_KEY, CMPSAVE_KEY, 'cardb_lang'];
window.exportData = function() {
    const payload = {
        app: 'cardb',
        version: 1,
        exported: new Date().toISOString(),
        data: {}
    };
    EXPORT_KEYS.forEach(k => {
        const v = localStorage.getItem(k);
        if (v != null) payload.data[k] = v;
    });
    const blob = new Blob([JSON.stringify(payload, null, 2)], {
        type: 'application/json'
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'cardb-backup-' + new Date().toISOString().slice(0, 10) + '.json';
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    showToast(t('export_done'));
};
window.importData = function(input) {
    const file = input.files && input.files[0];
    input.value = '';
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
        let data = null;
        try {
            const p = JSON.parse(reader.result);
            data = p && p.data;
        } catch (_) {}
        if (!data || typeof data !== 'object') {
            showToast(t('import_error'));
            return;
        }
        let langChanged = false,
            applied = 0;
        EXPORT_KEYS.forEach(k => {
            if (typeof data[k] !== 'string') return;
            if (k === 'cardb_lang' && data[k] !== getLang()) langChanged = true;
            localStorage.setItem(k, data[k]);
            applied++;
        });
        if (!applied) {
            showToast(t('import_error'));
            return;
        }
        updateSavedCount();
        renderSaved();
        if (typeof renderRecent === 'function') renderRecent();
        if (langChanged) setLang(data['cardb_lang']);
        showToast(t('import_done'));
    };
    reader.readAsText(file);
};

const IC_SEARCH_SM = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/></svg>';
const IC_CLOCK = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/></svg>';
const IC_EYE = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 12c.7-2 4-6 9-6s8.3 4 9 6c-.7 2-4 6-9 6s-8.3-4-9-6z"/><circle cx="12" cy="12" r="2.5"/></svg>';

function renderSaved() {
    const cars = getSavedCars(),
        searches = lsGet(LS_SEARCHES),
        hist = lsGet(LS_HIST);
    let h = '';
    const carLimit = _drawerShown.cars || _DRAWER_PAGE;
    h += `<div class="drawer-sec"><span class="drawer-sec-h">${ICON_HEART}${t('saved_cars_h')} · ${cars.length}</span>${cars.length ? `<button class="drawer-clear" onclick="clearSavedCars()">${t('clear_all')}</button>` : ''}</div>`;
    h += cars.length ? cars.slice(0, carLimit).map(c => `
        <div class="saved-row">
          <div class="grow flex items-center gap-3" data-key="${escapeHtml(c.key)}" data-act="open">
            <img src="${escapeHtml(c.thumb || '')}" alt="" onerror="this.style.visibility='hidden'">
            <div class="min-w-0"><div class="saved-row-title">${escapeHtml(c.title || c.key)}</div>${c.price ? `<div class="saved-row-price">${Number(c.price).toLocaleString()} ${escapeHtml(c.currency || '')}</div>` : ''}</div>
          </div>
          <button class="row-x" data-key="${escapeHtml(c.key)}" data-act="remove">✕</button>
        </div>`).join('') + _loadMore('cars', cars.length, carLimit) : `<div class="drawer-empty">${t('no_saved')}</div>`;

    h += `<div class="drawer-sec"><span class="drawer-sec-h">${IC_SEARCH_SM}${t('saved_searches_h')} · ${searches.length}</span>${searches.length ? `<button class="drawer-clear" onclick="clearSavedSearches()">${t('clear_all')}</button>` : ''}</div>`;
    const searchLimit = _drawerShown.searches || _DRAWER_PAGE;
    h += searches.length ? searches.slice(0, searchLimit).map((s, i) => _searchChip({
        runKind: 'search',
        delKind: 'search',
        i,
        item: s,
        uid: 'sdd-s-' + i,
        saved: true
    })).join('') + _loadMore('searches', searches.length, searchLimit) : `<div class="drawer-empty">-</div>`;

    const compSaves = getCompSaves();
    h += `<div class="drawer-sec"><span class="drawer-sec-h">${ICON_COMPARE}${t('saved_comparisons_h')} · ${compSaves.length}</span></div>`;
    h += compSaves.length ? compSaves.map((s, i) => `
        <div class="saved-row">
          <div class="grow flex items-center gap-3" data-act="loadcmp" data-i="${i}" style="cursor:pointer">
            <div class="cmp-save-thumbs">${s.cars.slice(0, 4).map(c => `<img src="${escapeHtml(c.thumb || '')}" alt="" onerror="this.style.visibility='hidden'">`).join('')}</div>
            <div class="saved-row-title">${t('cmp_cars_n', { n: s.cars.length })}</div>
          </div>
          <button class="row-x" data-act="delcmp" data-i="${i}" aria-label="${escapeHtml(t('remove'))}">✕</button>
        </div>`).join('') : `<div class="drawer-empty">-</div>`;

    h += `<div class="drawer-sec"><span class="drawer-sec-h">${IC_CLOCK}${t('recent_h')}</span>${hist.length ? `<button class="drawer-clear" onclick="clearHistory()">${t('clear_all')}</button>` : ''}</div>`;
    const histLimit = _drawerShown.hist || _DRAWER_PAGE;
    h += hist.length ? hist.slice(0, histLimit).map((q, i) => _searchChip({
        runKind: 'hist',
        delKind: 'hist',
        i,
        item: q,
        uid: 'sdd-h-' + i,
        saved: false
    })).join('') + _loadMore('hist', hist.length, histLimit) : `<div class="drawer-empty">-</div>`;

    const viewed = lsGet(LS_VIEWED);
    const viewedLimit = _drawerShown.viewed || _DRAWER_PAGE;
    h += `<div class="drawer-sec"><span class="drawer-sec-h">${IC_EYE}${t('viewed_h')} · ${viewed.length}</span>${viewed.length ? `<button class="drawer-clear" onclick="clearViewed()">${t('clear_all')}</button>` : ''}</div>`;
    h += viewed.length ? viewed.slice(0, viewedLimit).map(c => `
        <div class="saved-row">
          <div class="grow flex items-center gap-3" data-key="${escapeHtml(c.key)}" data-act="open">
            <img src="${escapeHtml(c.thumb || '')}" alt="" onerror="this.style.visibility='hidden'">
            <div class="min-w-0"><div class="saved-row-title">${escapeHtml(c.title || c.key)}</div>${c.price ? `<div class="saved-row-price">${Number(c.price).toLocaleString()} ${escapeHtml(c.currency || '')}</div>` : ''}</div>
          </div>
        </div>`).join('') + _loadMore('viewed', viewed.length, viewedLimit) : `<div class="drawer-empty">-</div>`;

    const hiddenList = getHiddenList();
    const hiddenLimit = _drawerShown.hidden || _DRAWER_PAGE;
    h += `<div class="drawer-sec"><span class="drawer-sec-h">${ICON_HIDE}${t('hidden_h')} · ${hiddenList.length}</span>${hiddenList.length ? `<button class="drawer-clear" onclick="clearHidden()">${t('clear_all')}</button>` : ''}</div>`;
    h += hiddenList.length ? hiddenList.slice(0, hiddenLimit).map(c => `
        <div class="saved-row">
          <div class="grow flex items-center gap-3" data-key="${escapeHtml(c.key)}" data-act="open" style="cursor:pointer">
            <img src="${escapeHtml(c.thumb || '')}" alt="" onerror="this.style.visibility='hidden'">
            <div class="saved-row-title">${escapeHtml(c.title || c.key)}</div>
          </div>
          <button class="row-x" data-act="unhide" data-key="${escapeHtml(c.key)}" title="${escapeHtml(t('act_undo'))}" aria-label="${escapeHtml(t('act_undo'))}">↩</button>
        </div>`).join('') + _loadMore('hidden', hiddenList.length, hiddenLimit) : `<div class="drawer-empty">-</div>`;

    const body = document.getElementById('saved-body');
    body.innerHTML = h;
    body.querySelectorAll('[data-act="open"]').forEach(el => el.onclick = (e) => {
        goToCarDetail(el.dataset.key, e);
        closeSaved();
    });
    body.querySelectorAll('[data-act="remove"]').forEach(el => el.onclick = () => {
        toggleSave(el.dataset.key);
        renderSaved();
    });
    body.querySelectorAll('[data-act="loadcmp"]').forEach(el => el.onclick = () => loadComparison(+el.dataset.i));
    body.querySelectorAll('[data-act="delcmp"]').forEach(el => el.onclick = () => deleteComparison(+el.dataset.i));
    body.querySelectorAll('[data-act="unhide"]').forEach(el => el.onclick = (e) => {
        e.stopPropagation();
        unhideCar(el.dataset.key);
    });
    body.querySelectorAll('[data-more]').forEach(el => el.onclick = () => drawerShowMore(el.dataset.more));
    _wireChipExpand(body);
    body.querySelectorAll('.hist-chip[data-kind]').forEach(b => {
        b.onclick = () => {
            if (b.dataset.kind === 'search') {
                const s = lsGet(LS_SEARCHES)[+b.dataset.i];
                if (s) runSavedSearch(s);
            } else {
                const q = lsGet(LS_HIST)[+b.dataset.i];
                if (q) runHistory(q);
            }
        };
    });
    body.querySelectorAll('.chip-del').forEach((b) => {
        b.onclick = (e) => {
            e.stopPropagation();
            const lk = b.dataset.kind === 'search' ? LS_SEARCHES : LS_HIST;
            const a = lsGet(lk);
            a.splice(+b.dataset.i, 1);
            lsSet(lk, a);
            updateSavedCount();
            renderSaved();
            renderRecent();
        };
    });
}

window.clearSearchInput = function() {
    const el = document.getElementById('search-input');
    el.value = '';
    el.focus();
    document.getElementById('clear-search').classList.add('hidden');
};

(function wireExtras() {
    const el = document.getElementById('search-input'),
        x = document.getElementById('clear-search');
    if (el && x) {
        const tog = () => x.classList.toggle('hidden', !el.value);
        el.addEventListener('input', tog);
        tog();
    }
    updateSavedCount();
    renderRecent();
    document.addEventListener('keydown', (e) => {
        if (e.key !== 'Escape') return;
        if (!document.querySelector('#saved-drawer.open')) return;
        if (_lightbox) return;
        const cm = document.getElementById('cmp-modal');
        if (cm && cm.classList.contains('show')) return;
        closeSaved();
    });
})();

window.addEventListener('popstate', () => {
    if (_lightbox) closeLightbox();
    const cm = document.getElementById('cmp-modal');
    if (cm && cm.classList.contains('show')) closeCompare();
    if (document.querySelector('#saved-drawer.open')) closeSaved();
    const sb = document.getElementById('filter-sidebar');
    if (sb && sb.classList.contains('open')) {
        sb.classList.remove('open');
        unlockScroll('sheet');
    }
    const route = parseRoute();
    if (route.view === 'detail') {
        showDetailView(route.key);
        window.scrollTo(0, 0);
    } else if (route.view === 'notfound') showNotFound();
    else {
        showSearchView();
        requestAnimationFrame(() => window.scrollTo(0, _searchScrollY));
    }
});

(function bootRoute() {
    const route = parseRoute();
    if (route.view === 'detail') showDetailView(route.key);
    else if (route.view === 'notfound') showNotFound();
})();

// keepSize=true only re-anchors position on scroll. the size is frozen at open time
// so scrolling never shrinks the panel
function _placeCddPanel(btn, panel, keepSize) {
    const r = btn.getBoundingClientRect();
    if (!keepSize) {
        panel.style.width = 'auto';
        panel.style.minWidth = r.width + 'px';
        panel.style.maxWidth = Math.min(380, window.innerWidth - 16) + 'px';
    }
    const pw = Math.min(panel.offsetWidth || r.width, window.innerWidth - 16);
    let left = r.left;
    if (left + pw > window.innerWidth - 8) left = window.innerWidth - pw - 8; // clamp right edge
    if (left < 8) left = 8;
    panel.style.left = left + 'px';
    const below = window.innerHeight - r.bottom - 10;
    const above = r.top - 10;
    const ph = Math.min(300, panel.scrollHeight || 300);
    if (below >= ph || below >= above) {
        panel.style.top = (r.bottom + 6) + 'px';
        panel.style.bottom = 'auto';
        if (!keepSize) panel.style.maxHeight = Math.max(120, Math.min(300, below)) + 'px';
    } else {
        panel.style.top = 'auto';
        panel.style.bottom = (window.innerHeight - r.top + 6) + 'px';
        if (!keepSize) panel.style.maxHeight = Math.max(120, Math.min(300, above)) + 'px';
    }
}

function enhanceDropdowns() {
    document.querySelectorAll('select.filter-select').forEach(enhanceSelect);
    const closeAll = () => {
        document.body.classList.remove('cdd-open');
        document.querySelectorAll('.cdd.open').forEach(d => {
            d.classList.remove('open');
            const b = d.querySelector('.cdd-btn');
            if (b) {
                b.setAttribute('aria-expanded', 'false');
                b.removeAttribute('aria-activedescendant');
            }
        });
    };
    document.addEventListener('click', closeAll);
    window.addEventListener('resize', closeAll);
    window.addEventListener('scroll', (e) => {
        const open = document.querySelector('.cdd.open');
        if (!open) return;
        const panel = open.querySelector('.cdd-panel');
        // scrolling inside the panel must not reflow it (that was shrinking the panel)
        if (panel.contains(e.target)) return;
        const btn = open.querySelector('.cdd-btn');
        const r = btn.getBoundingClientRect();
        if (r.bottom < 4 || r.top > window.innerHeight - 4) {
            closeAll();
            return;
        }
        _placeCddPanel(btn, panel, true);
    }, true);
}

const CDD_TICK = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3.5 8.5l3 3 6-7"/></svg>';

function enhanceSelect(sel) {
    if (sel._cdd) return;
    const multi = sel.multiple;
    const searchable = sel.dataset.search != null;
    let _filter = '';
    const _expanded = new Set(); // collapsed-by-default series groups (by header index)
    const wrap = document.createElement('div');
    wrap.className = 'cdd';
    sel.parentNode.insertBefore(wrap, sel);
    wrap.appendChild(sel);
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'cdd-btn';
    const panel = document.createElement('div');
    panel.className = 'cdd-panel';
    wrap.append(btn, panel);

    const _uid = 'cdd' + (enhanceSelect._n = (enhanceSelect._n || 0) + 1);
    const listId = _uid + '-list';
    btn.id = _uid + '-btn';
    btn.setAttribute('role', 'combobox');
    btn.setAttribute('aria-haspopup', 'listbox');
    btn.setAttribute('aria-expanded', 'false');
    btn.setAttribute('aria-controls', listId);
    const _lbl = (sel.closest('.filter-group') || wrap.parentNode || document).querySelector('.filter-label');
    if (_lbl) {
        if (!_lbl.id) _lbl.id = _uid + '-lbl';
        btn.setAttribute('aria-labelledby', _lbl.id);
    }

    const realSel = () => Array.from(sel.selectedOptions).filter(o => o.value);
    const anyLabel = () => {
        const a = Array.from(sel.options).find(o => !o.value);
        return a ? a.textContent : '';
    };

    const updateLabel = () => {
        if (multi) {
            const s = realSel();
            const totalOpts = Array.from(sel.options).filter(o => o.value).length;
            // none OR all selected both read as "all" - show the placeholder, not a wall of chips
            if (!s.length || (totalOpts && s.length === totalOpts)) {
                btn.innerHTML = `<span class="cdd-label is-empty">${escapeHtml(anyLabel())}</span><span class="cdd-chev">▾</span>`;
                return;
            }
            const MAX = 2;
            const chips = s.slice(0, MAX).map(o => {
                const logo = sel.id === 'f-brand' ?
                    `<img class="brand-logo" src="logos/${_brandLogoSlug(o.textContent)}.png" alt="" onerror="this.remove()">` :
                    '';
                return `<span class="cdd-chip">${logo}${escapeHtml(o.textContent)}</span>`;
            }).join('');
            const more = s.length > MAX ? `<span class="cdd-count">+${s.length - MAX}</span>` : '';
            btn.innerHTML = `<span class="cdd-chips">${chips}</span>${more}<span class="cdd-chev">▾</span>`;
        } else {
            const cur = sel.options[sel.selectedIndex];
            btn.innerHTML = `<span class="cdd-label">${escapeHtml(cur ? cur.textContent : '')}</span><span class="cdd-chev">▾</span>`;
        }
    };

    // grouped multi-select: a group header can toggle all its members at once
    const _groupMembers = (gi) => {
        const out = [];
        for (let j = gi + 1; j < sel.options.length; j++) {
            const o = sel.options[j];
            if (o.disabled) break;
            if (o.value) out.push(j);
        }
        return out;
    };
    const _groupState = (gi) => {
        const m = _groupMembers(gi);
        if (!m.length) return 'none';
        const c = m.filter(j => sel.options[j].selected).length;
        return c === 0 ? 'none' : c === m.length ? 'all' : 'some';
    };
    const _allValueIdx = () => {
        const out = [];
        for (let j = 0; j < sel.options.length; j++) {
            const o = sel.options[j];
            if (o.value && !o.disabled) out.push(j);
        }
        return out;
    };
    const _allState = () => {
        const a = _allValueIdx();
        if (!a.length) return 'none';
        const c = a.filter(j => sel.options[j].selected).length;
        return c === 0 ? 'none' : c === a.length ? 'all' : 'some';
    };
    const _boxCls = (st) => st === 'all' ? 'on' : st === 'some' ? 'mixed' : '';

    const rowsHtml = () => {
        let group = null; // index of the current series header (or null = ungrouped)
        const rows = Array.from(sel.options).map((o, i) => {
            if (o.disabled) {
                if (multi && searchable && _filter) return ''; // hide headers while searching
                if (o.textContent) {
                    group = i;
                    const label = o.textContent;
                    const brand = o.dataset.brand || '';
                    const mono = (label.split('·').pop() || '').trim().charAt(0).toUpperCase();
                    const n = o.dataset.n || '';
                    // model groups show the brand's logo, with an initials fallback. other
                    // grouped dropdowns fall back to the class letter
                    const badge = brand ? _brandBadge(brand) : `<span class="grp-badge">${escapeHtml(mono)}</span>`;
                    const gst = _groupState(i);
                    const gcheck = multi ? `<span class="grp-check cdd-box ${_boxCls(gst)}" data-groupcheck="${i}" role="checkbox" aria-checked="${gst === 'all' ? 'true' : gst === 'some' ? 'mixed' : 'false'}" aria-label="${escapeHtml(t('select_all_group'))}">${CDD_TICK}</span>` : '';
                    return `<div class="cdd-group-head cdd-grp ${_expanded.has(i) ? 'open' : ''}" id="${listId}-o${i}" role="option" aria-selected="false" aria-expanded="${_expanded.has(i) ? 'true' : 'false'}" data-group="${i}">` +
                        gcheck + badge +
                        `<span class="grp-label">${escapeHtml(label)}</span>` +
                        (n ? `<span class="grp-n">${escapeHtml(n)}</span>` : '') +
                        `<svg class="grp-chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 6l6 6-6 6"/></svg></div>`;
                }
                group = null;
                return `<div class="cdd-sep" role="presentation"></div>`;
            }
            if (multi) {
                // every multi-select has a "select all" master row, so drop the "any" placeholder
                if (!o.value) return '';
                const collapsed = group !== null && !_expanded.has(group) && !(searchable && _filter);
                if (collapsed) return '';
                if (searchable && _filter && o.value && !_matchFilter(o.textContent, _filter)) return '';
                const badge = (sel.id === 'f-brand' && o.value) ? _brandBadge(o.textContent) : '';
                const facetIc = o.value ? (
                    sel.id === 'f-body' ? _bodyIcon(o.value) :
                    sel.id === 'f-fuel' ? _fuelIcon(o.value) :
                    sel.id === 'f-gearbox' ? _gearIcon(o.value) :
                    sel.id === 'f-drive' ? _driveIcon(o.value) :
                    sel.id === 'f-location' ? _PIC('<path d="M12 21s-6-5.2-6-10a6 6 0 0 1 12 0c0 4.8-6 10-6 10z"/><circle cx="12" cy="11" r="2.2"/>') : '') : '';
                return `<div class="cdd-opt cdd-check ${o.selected ? 'on' : ''}" id="${listId}-o${i}" role="option" aria-selected="${o.selected ? 'true' : 'false'}" data-i="${i}"><span class="cdd-box ${o.selected ? 'on' : ''}">${CDD_TICK}</span>${badge}${facetIc}${escapeHtml(o.textContent)}</div>`;
            }
            const singleIc = sel.id === 'f-sort' ? _sortIcon(o.value) : (sel.id === 'f-customs' ? _customsIcon(o.value) : '');
            return `<div class="cdd-opt ${i === sel.selectedIndex ? 'on' : ''}" id="${listId}-o${i}" role="option" aria-selected="${i === sel.selectedIndex ? 'true' : 'false'}" data-i="${i}">${singleIc}${escapeHtml(o.textContent)}</div>`;
        }).join('');
        // a "select all" master row for every multi-select, when not filtering
        const selectAll = (multi && !_filter && _allValueIdx().length) ?
            `<div class="cdd-opt cdd-check cdd-selectall" data-selectall="1" role="option"><span class="cdd-box ${_boxCls(_allState())}">${CDD_TICK}</span>${escapeHtml(t('select_all_models'))}</div>` :
            '';
        return selectAll + rows;
    };
    // in-place sync so a toggle animates the box instead of re-rendering every row
    const _syncOptRow = (i) => {
        const el = panel.querySelector(`.cdd-opt[data-i="${i}"]`);
        if (!el) return;
        const on = sel.options[i].selected;
        el.classList.toggle('on', on);
        el.setAttribute('aria-selected', on ? 'true' : 'false');
        const box = el.querySelector('.cdd-box');
        if (box) {
            box.classList.remove('mixed');
            box.classList.toggle('on', on);
        }
    };
    const _syncGroupChecks = () => {
        panel.querySelectorAll('[data-groupcheck]').forEach(gc => {
            const st = _groupState(+gc.dataset.groupcheck);
            gc.classList.toggle('on', st === 'all');
            gc.classList.toggle('mixed', st === 'some');
            gc.setAttribute('aria-checked', st === 'all' ? 'true' : st === 'some' ? 'mixed' : 'false');
        });
    };
    const _syncSelectAll = () => {
        const sa = panel.querySelector('[data-selectall] .cdd-box');
        if (!sa) return;
        const st = _allState();
        sa.classList.toggle('on', st === 'all');
        sa.classList.toggle('mixed', st === 'some');
    };

    const render = () => {
        wrap.classList.toggle('disabled', sel.disabled);
        updateLabel();
        const _ph = escapeHtml(t(sel.dataset.searchPh || ''));
        const sb = (multi && searchable) ?
            `<input class="cdd-search" type="text" maxlength="40" aria-controls="${listId}" aria-autocomplete="list" aria-label="${_ph}" placeholder="${_ph}" value="${escapeHtml(_filter)}">` :
            '';
        panel.innerHTML = sb + `<div class="cdd-rows" id="${listId}" role="listbox"${multi ? ' aria-multiselectable="true"' : ''}>${rowsHtml()}</div>`;
        if (multi && searchable) {
            const si = panel.querySelector('.cdd-search');
            si.addEventListener('click', (e) => e.stopPropagation());
            // short debounce - matching transliterates every option, too heavy per keystroke
            si.addEventListener('input', () => {
                clearTimeout(si._deb);
                si._deb = setTimeout(() => {
                    _filter = si.value.trim().toLowerCase();
                    panel.querySelector('.cdd-rows').innerHTML = rowsHtml();
                    if (wrap.classList.contains('open')) setActive(0);
                }, 80);
            });
        }
    };

    btn.addEventListener('click', (e) => {
        e.stopPropagation();
        if (sel.disabled) return;
        wrap.classList.contains('open') ? closePanel(false) : openPanel('first');
    });
    const _clearAny = () => {
        const any = Array.from(sel.options).find(x => !x.value);
        if (any) any.selected = false;
    };
    panel.addEventListener('click', (e) => {
        // group header's select-all checkbox - toggle every model in the class
        const gcheck = e.target.closest('[data-groupcheck]');
        if (gcheck) {
            e.stopPropagation();
            const gi = +gcheck.dataset.groupcheck;
            const members = _groupMembers(gi);
            const turnOn = _groupState(gi) !== 'all';
            members.forEach(j => sel.options[j].selected = turnOn);
            if (turnOn) _clearAny();
            sel.dispatchEvent(new Event('change', {
                bubbles: true
            }));
            members.forEach(_syncOptRow);
            _syncGroupChecks();
            _syncSelectAll();
            updateLabel();
            return;
        }
        // "select all models" master row
        const sa = e.target.closest('[data-selectall]');
        if (sa) {
            e.stopPropagation();
            const all = _allValueIdx();
            const turnOn = _allState() !== 'all';
            all.forEach(j => sel.options[j].selected = turnOn);
            _clearAny();
            sel.dispatchEvent(new Event('change', {
                bubbles: true
            }));
            const rowsEl = panel.querySelector('.cdd-rows');
            if (rowsEl) rowsEl.innerHTML = rowsHtml();
            updateLabel();
            return;
        }
        const grp = e.target.closest('.cdd-grp');
        if (grp) {
            e.stopPropagation();
            const gi = +grp.dataset.group;
            _expanded.has(gi) ? _expanded.delete(gi) : _expanded.add(gi);
            const rowsEl = panel.querySelector('.cdd-rows');
            if (rowsEl) rowsEl.innerHTML = rowsHtml();
            return;
        }
        const opt = e.target.closest('.cdd-opt');
        if (!opt) return;
        if (multi) e.stopPropagation(); // keep panel open for multi-select
        const i = +opt.dataset.i;
        if (multi) {
            const o = sel.options[i];
            if (!o.value) {
                Array.from(sel.options).forEach(x => x.selected = false);
                sel.dispatchEvent(new Event('change', {
                    bubbles: true
                }));
                const rowsEl = panel.querySelector('.cdd-rows');
                if (rowsEl) rowsEl.innerHTML = rowsHtml();
            } else {
                o.selected = !o.selected;
                _clearAny();
                sel.dispatchEvent(new Event('change', {
                    bubbles: true
                }));
                _syncOptRow(i);
                _syncGroupChecks();
                _syncSelectAll();
            }
            updateLabel();
        } else {
            sel.selectedIndex = i;
            sel.dispatchEvent(new Event('change', {
                bubbles: true
            }));
            closePanel(false);
            render();
        }
    });

    let _activeIdx = -1;
    const focusOwner = () => (multi && searchable) ? panel.querySelector('.cdd-search') : btn;
    const rowEls = () => Array.from(panel.querySelectorAll('.cdd-rows > .cdd-opt, .cdd-rows > .cdd-grp'));
    const setActive = (idx) => {
        const rows = rowEls();
        if (!rows.length) {
            _activeIdx = -1;
            const fo = focusOwner();
            if (fo) fo.removeAttribute('aria-activedescendant');
            return;
        }
        _activeIdx = Math.max(0, Math.min(idx, rows.length - 1));
        rows.forEach(r => r.classList.remove('cdd-active'));
        const el = rows[_activeIdx];
        el.classList.add('cdd-active');
        const fo = focusOwner();
        if (fo) fo.setAttribute('aria-activedescendant', el.id);
        el.scrollIntoView({
            block: 'nearest'
        });
    };
    const openPanel = (at) => {
        if (sel.disabled) return;
        document.querySelectorAll('.cdd.open').forEach(d => {
            d.classList.remove('open');
            const b = d.querySelector('.cdd-btn');
            if (b) b.setAttribute('aria-expanded', 'false');
        });
        _filter = '';
        render();
        wrap.classList.add('open');
        btn.setAttribute('aria-expanded', 'true');
        document.body.classList.add('cdd-open'); // lifts the sidebar's stacking context above the results
        _placeCddPanel(btn, panel);
        panel.scrollTop = 0;
        const fo = focusOwner();
        if (fo && fo !== btn) fo.focus();
        setActive(at === 'last' ? rowEls().length - 1 : 0);
    };
    const closePanel = (focusBtn) => {
        wrap.classList.remove('open');
        btn.setAttribute('aria-expanded', 'false');
        document.body.classList.remove('cdd-open');
        const fo = focusOwner();
        if (fo) fo.removeAttribute('aria-activedescendant');
        _activeIdx = -1;
        if (focusBtn) btn.focus();
    };
    const activateRow = () => {
        const rows = rowEls();
        const el = rows[_activeIdx];
        if (!el) return;
        if (el.classList.contains('cdd-grp')) {
            const gi = +el.dataset.group;
            _expanded.has(gi) ? _expanded.delete(gi) : _expanded.add(gi);
            const rowsEl = panel.querySelector('.cdd-rows');
            if (rowsEl) rowsEl.innerHTML = rowsHtml();
            const same = panel.querySelector(`[data-group="${gi}"]`);
            const ni = rowEls().indexOf(same);
            setActive(ni >= 0 ? ni : 0);
        } else if (multi) {
            el.click();
            setActive(_activeIdx); // rows re-render on multi-select; re-anchor highlight
        } else {
            el.click(); // single-select click closes the panel
        }
    };
    const onKey = (e) => {
        if (sel.disabled) return;
        if (!wrap.classList.contains('open')) {
            if (e.key === 'ArrowDown' || e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                openPanel('first');
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                openPanel('last');
            }
            return;
        }
        switch (e.key) {
            case 'ArrowDown':
                e.preventDefault();
                setActive(_activeIdx + 1);
                break;
            case 'ArrowUp':
                e.preventDefault();
                setActive(_activeIdx - 1);
                break;
            case 'Home':
                e.preventDefault();
                setActive(0);
                break;
            case 'End':
                e.preventDefault();
                setActive(rowEls().length - 1);
                break;
            case 'Enter':
                e.preventDefault();
                activateRow();
                break;
            case ' ':
                if (e.target.classList && e.target.classList.contains('cdd-search')) return; // let space type
                e.preventDefault();
                activateRow();
                break;
            case 'Escape':
                e.preventDefault();
                closePanel(true);
                break;
            case 'Tab':
                closePanel(false);
                break;
        }
    };
    wrap.addEventListener('keydown', onKey);
    sel.addEventListener('change', () => {
        wrap.classList.contains('open') ? updateLabel() : render();
    });
    new MutationObserver((muts) => {
        if (muts.some(m => m.type === 'childList')) _expanded.clear();
        render();
    }).observe(sel, {
        childList: true,
        attributes: true,
        attributeFilter: ['disabled']
    });
    sel._cdd = {
        render
    };
    render();
}

function refreshDropdowns() {
    document.querySelectorAll('select.filter-select').forEach(s => s._cdd && s._cdd.render());
}

const _FILTER_ICONS = {
    brand: '<path d="M20.6 13.4 13.4 20.6a2 2 0 0 1-2.8 0l-6.2-6.2a2 2 0 0 1-.6-1.4V5a1 1 0 0 1 1-1h7a2 2 0 0 1 1.4.6l6.4 6.4a2 2 0 0 1 0 2.8z"/><circle cx="8" cy="8" r="1.4"/>',
    model: '<path d="M5 11l1.5-4.2A2 2 0 0 1 8.4 5.5h7.2a2 2 0 0 1 1.9 1.3L19 11M4.5 11h15v3.5a1 1 0 0 1-1 1H17a1 1 0 0 1-1-1v-.5H8v.5a1 1 0 0 1-1 1H5.5a1 1 0 0 1-1-1z"/><circle cx="7.5" cy="13" r="1"/><circle cx="16.5" cy="13" r="1"/>',
    year: '<rect x="4" y="5" width="16" height="15" rx="2"/><path d="M4 9h16M8 3v4M16 3v4"/>',
    price: '<circle cx="12" cy="12" r="9"/><path d="M14.5 9.3A2.4 2.4 0 0 0 12 8c-1.4 0-2.5.9-2.5 2s1.1 1.9 2.5 1.9 2.5.9 2.5 2-1.1 2-2.5 2a2.4 2.4 0 0 1-2.5-1.4M12 6.5v11"/>',
    mileage: '<path d="M13.4 13.4l2.6-2.6"/><path d="M3.6 15a9 9 0 1 1 16.8 0"/>',
    body_type: '<rect x="4" y="4" width="7" height="7" rx="1.5"/><rect x="13" y="4" width="7" height="7" rx="1.5"/><rect x="4" y="13" width="7" height="7" rx="1.5"/><rect x="13" y="13" width="7" height="7" rx="1.5"/>',
    fuel: '<path d="M6 21V5.5A2.5 2.5 0 0 1 8.5 3h3A2.5 2.5 0 0 1 14 5.5V21"/><path d="M4 21h12M8 8h4"/><path d="M14 9l2.4 2.4c.4.4.6.9.6 1.4V17a1.5 1.5 0 0 0 3 0V9.5"/>',
    gearbox: '<circle cx="6" cy="5" r="1.5"/><circle cx="12" cy="5" r="1.5"/><circle cx="18" cy="5" r="1.5"/><path d="M6 6.5v4h12v-4M12 10.5v8.5M10 19h4"/>',
    drive: '<circle cx="6.5" cy="7" r="2.5"/><circle cx="17.5" cy="7" r="2.5"/><circle cx="6.5" cy="17" r="2.5"/><circle cx="17.5" cy="17" r="2.5"/><path d="M6.5 7h11M6.5 17h11M6.5 7v10M17.5 7v10"/>',
    location: '<path d="M12 21s-6-5.2-6-10a6 6 0 0 1 12 0c0 4.8-6 10-6 10z"/><circle cx="12" cy="11" r="2.2"/>',
    customs: '<path d="M12 3l7 3v5c0 4.5-3 7.8-7 9-4-1.2-7-4.5-7-9V6z"/><path d="M9 12l2 2 4-4"/>',
};

function addFilterIcons() {
    document.querySelectorAll('.sidebar .filter-group[data-filter]').forEach(g => {
        if (g.querySelector(':scope > .fl-icon')) return;
        const paths = _FILTER_ICONS[g.dataset.filter];
        if (!paths) return;
        const span = document.createElement('span');
        span.className = 'fl-icon';
        span.setAttribute('aria-hidden', 'true');
        span.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">${paths}</svg>`;
        g.insertBefore(span, g.firstChild);
    });
}

loadStats();
const _makesReady = loadMakes();
const _facetsReady = loadFacets();

// first-load overlay: hide once the filter data lands, or after a safety cap so a
// slow/cold backend never traps the user behind the blur
(function bootOverlay() {
    const ov = document.getElementById('boot-overlay');
    if (!ov) return;
    let done = false;
    const hide = () => {
        if (done) return;
        done = true;
        ov.classList.add('hidden');
        setTimeout(() => ov.remove(), 500);
    };
    Promise.all([_makesReady, _facetsReady]).then(hide);
    setTimeout(hide, 12000);
})();

enhanceDropdowns();
initMileageSlider();
updateSearchBtnCount();
renderCompareBar();
addFilterIcons();

(function restoreFromUrl() {
    if (parseRoute().view !== 'search' || !location.search) return;
    const p = paramsToPayload(new URLSearchParams(location.search));
    const page = p.page;
    delete p.page;
    if (!Object.keys(p).length) return;
    const needsOptions = Object.values(_URL_LISTS).some(f => p[f]);
    (needsOptions ? Promise.all([_makesReady, _facetsReady]) : Promise.resolve()).then(() => {
        applySearchPayload(p);
        currentPage = page || 1;
        doSearch({
            resetPage: false
        });
    });
})();

if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', refreshDropdowns);
else refreshDropdowns();

document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !_lightbox) {
        const m = document.getElementById('cmp-modal');
        if (m && m.classList.contains('show')) closeCompare();
    }
});