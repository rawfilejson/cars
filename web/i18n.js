// Translations dictionary. Default language is Georgian.
// Switch persists in localStorage.

const TRANSLATIONS = {
    ka: {
        nav_listings_count: "{n} განცხადება",
        hero_title: "მანქანის ისტორია — ერთი ძიებით",
        hero_desc_html:
            "<strong>autopapa.ge</strong> და <strong>myauto.ge</strong>-ის " +
            "განცხადებები ერთად. ეძებე VIN-ით, ნომრით, ან კონკრეტული აღწერით " +
            "(მაგ. <em>Toyota Camry 2020 თბილისი</em>).",
        notice_date_html:
            "📅 მონაცემთა შენახვა დავიწყეთ <strong>2026 წლის 10 მაისიდან</strong> — " +
            "ამაზე ადრინდელი განცხადებები ბაზაში არ არის.",
        notice_slow_html:
            "⏱ <strong>თავისუფალი ტექსტი</strong> ხანდახან რამდენიმე წამს " +
            "მოითხოვს — ვამოწმებთ ბაზის ყველა აღწერას.",
        tab_vin: "VIN",
        tab_phone: "ნომერი",
        tab_text: "სხვა ინფორმაცია",
        ph_vin: "შეიყვანე VIN (17 სიმბოლო)",
        ph_phone: "შეიყვანე ნომერი (მაგ. 555555555)",
        ph_text: "მაგ. Toyota Camry 2020 თბილისი",
        btn_search: "ძიება",
        btn_searching: "ძიება...",
        empty_state: "შეიყვანე ძიების მონაცემები ზემოთ",
        results_count: "{n} შედეგი",
        results_remaining: " · ამ საათში დარჩა {n} ცდა",
        no_results: "ვერაფერი ვიპოვე 🤷‍♂️",
        err_fetch: "შეცდომა: {msg}",
        err_too_generic: "ძიება ძალიან ზოგადია — დაამატე წელი, ქალაქი ან მოდელის ვერსია (მაგ. Toyota Camry 2020 თბილისი).",
        cleared: "განბაჟებული",
        not_cleared: "განუბაჟებელი",
        more_photos: "+{n} ფოტო",
        view_source: "წყაროზე ნახვა →",
        footer_about: "მონაცემები autopapa.ge და myauto.ge-დან · ღია წყაროებიდან",
        footer_contact: "კონტაქტი:",
    },
    en: {
        nav_listings_count: "{n} listings",
        hero_title: "Car history — in one search",
        hero_desc_html:
            "Listings from <strong>autopapa.ge</strong> and " +
            "<strong>myauto.ge</strong>, in one place. Search by VIN, phone " +
            "number, or a specific description (e.g. <em>Toyota Camry 2020 Tbilisi</em>).",
        notice_date_html:
            "📅 We started collecting on <strong>May 10, 2026</strong> — " +
            "older listings are not in the database.",
        notice_slow_html:
            "⏱ <strong>Free-text</strong> queries can take a few seconds — " +
            "we scan every description.",
        tab_vin: "VIN",
        tab_phone: "Phone",
        tab_text: "Free text",
        ph_vin: "Enter VIN (17 characters)",
        ph_phone: "Enter phone (e.g. 555555555)",
        ph_text: "e.g. Toyota Camry 2020 Tbilisi",
        btn_search: "Search",
        btn_searching: "Searching...",
        empty_state: "Enter your search query above",
        results_count: "{n} results",
        results_remaining: " · {n} searches left this hour",
        no_results: "Nothing found 🤷‍♂️",
        err_fetch: "Error: {msg}",
        err_too_generic: "Search is too broad — add the year, city, or trim (e.g. Toyota Camry 2020 Tbilisi).",
        cleared: "Customs cleared",
        not_cleared: "Not cleared",
        more_photos: "+{n} photos",
        view_source: "View source →",
        footer_about: "Data from autopapa.ge and myauto.ge · open sources",
        footer_contact: "Contact:",
    },
};

const LANG_KEY = "car_lang";
const DEFAULT_LANG = "ka";

function getLang() {
    return localStorage.getItem(LANG_KEY) || DEFAULT_LANG;
}

function setLang(lang) {
    localStorage.setItem(LANG_KEY, lang);
    applyTranslations();
    // Notify any listeners (e.g. re-render search results)
    document.dispatchEvent(new CustomEvent("langchange", { detail: lang }));
}

function t(key, vars = {}) {
    const lang = getLang();
    const template = (TRANSLATIONS[lang] || TRANSLATIONS[DEFAULT_LANG])[key] || key;
    return template.replace(/\{(\w+)\}/g, (_, k) => vars[k] ?? "");
}

function applyTranslations() {
    const lang = getLang();
    document.documentElement.lang = lang;

    // Text content elements
    document.querySelectorAll("[data-i18n]").forEach((el) => {
        el.textContent = t(el.dataset.i18n);
    });

    // HTML elements (contain markup)
    document.querySelectorAll("[data-i18n-html]").forEach((el) => {
        el.innerHTML = t(el.dataset.i18nHtml);
    });

    // Placeholders
    document.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
        el.placeholder = t(el.dataset.i18nPlaceholder);
    });

    // Active state on language switcher
    document.querySelectorAll(".lang-btn").forEach((btn) => {
        btn.classList.toggle("font-bold", btn.dataset.lang === lang);
        btn.classList.toggle("text-white", btn.dataset.lang === lang);
        btn.classList.toggle("text-slate-400", btn.dataset.lang !== lang);
    });
}

// Apply on initial load
document.addEventListener("DOMContentLoaded", applyTranslations);

window.t = t;
window.getLang = getLang;
window.setLang = setLang;
