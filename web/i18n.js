// Translations dictionary. Default language is Georgian.
// Switch persists in localStorage.

const TRANSLATIONS = {
    ka: {
        nav_listings_count: "ბაზაში: {n} განცხადება",
        hero_title: "იპოვე განცხადება VIN კოდით",
        hero_desc_html:
            "ერთ ვებგვერდზე გავყავი <strong>autopapa.ge</strong> და " +
            "<strong>myauto.ge</strong>-ის ყველა განცხადება. ეძებე VIN კოდით, " +
            "ნომრით ან სხვა ინფორმაციით — <strong class=\"text-green-700\">" +
            "სრულიად უფასოდ, რეგისტრაციის გარეშე</strong>.",
        notice_date_html:
            "📅 <strong>გაითვალისწინე:</strong> მონაცემთა ბაზის შენახვა " +
            "დავიწყეთ <strong>2026 წლის 10 მაისიდან</strong>. ამ თარიღამდე " +
            "გამოქვეყნებული განცხადებები ბაზაში არ გვექნება.",
        tab_vin: "VIN კოდი",
        tab_phone: "ნომერი",
        tab_text: "სხვა ინფორმაცია",
        ph_vin: "შეიყვანე VIN კოდი (17 სიმბოლო)",
        ph_phone: "შეიყვანე ნომერი (555555555 ან +995555555555)",
        ph_text: "მაგალითად: Toyota Camry 2020 თბილისი",
        btn_search: "ძიება",
        btn_searching: "ძიება...",
        empty_state: "ჯერ ძიება არ გაგიკეთებიათ",
        results_count: "{n} შედეგი",
        results_remaining: " · ამ საათში დარჩა {n} ცდა",
        no_results: "ვერაფერი ვიპოვე ამ მოთხოვნით 🤷‍♂️",
        err_fetch: "შეცდომა: {msg}",
        cleared: "განბაჟებული",
        not_cleared: "განუბაჟებელი",
        more_photos: "+{n} ფოტო",
        view_source: "წყაროზე ნახვა →",
        footer_about: "მონაცემები autopapa.ge და myauto.ge-დან · ღია წყაროებიდან",
        footer_contact: "კონტაქტი:",
    },
    en: {
        nav_listings_count: "In DB: {n} listings",
        hero_title: "Find a listing by VIN",
        hero_desc_html:
            "Aggregated listings from <strong>autopapa.ge</strong> and " +
            "<strong>myauto.ge</strong>. Search by VIN, phone number, or " +
            "free text — <strong class=\"text-green-700\">free, no signup " +
            "required</strong>.",
        notice_date_html:
            "📅 <strong>Note:</strong> We started collecting data on " +
            "<strong>May 10, 2026</strong>. Listings published before that " +
            "date are not in the database.",
        tab_vin: "VIN",
        tab_phone: "Phone",
        tab_text: "Free text",
        ph_vin: "Enter VIN (17 characters)",
        ph_phone: "Enter phone (555555555 or +995555555555)",
        ph_text: "e.g.: Toyota Camry 2020 Tbilisi",
        btn_search: "Search",
        btn_searching: "Searching...",
        empty_state: "No search yet",
        results_count: "{n} results",
        results_remaining: " · {n} searches left this hour",
        no_results: "Nothing found for this query 🤷‍♂️",
        err_fetch: "Error: {msg}",
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
