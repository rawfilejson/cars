// Two-language dictionary. KA is the default — Georgian users come first.
// Switch persists via localStorage.

const TRANSLATIONS = {
    ka: {
        brand_name: "Car-DB",
        brand_sub: "მანქანების ბაზა",
        nav_listings_count: "{n} განცხადება",

        hero_title: "ერთი ძიება. ყველა განცხადება.",
        hero_desc:
            "autopapa.ge და myauto.ge-ის გაერთიანებული ბაზა — VIN-ით, " +
            "ნომრით, ან კონკრეტული აღწერით.",

        ph_query: "VIN, ნომერი, ბრენდი, მოდელი, წელი, ქალაქი...",

        filters_toggle: "ფილტრები",
        filter_year:    "წელი",
        filter_price:   "ფასი (USD)",
        filter_mileage: "გარბენი (კმ)",
        filter_from:    "დან",
        filter_to:      "მდე",
        filter_sort:    "სორტირება",
        filter_clear:   "ფილტრების გასუფთავება",

        sort_newest:      "ახალი ბოლოს",
        sort_price_asc:   "ფასი იაფიდან",
        sort_price_desc:  "ფასი ძვირიდან",
        sort_year_desc:   "წელი ახლიდან",
        sort_year_asc:    "წელი ძველიდან",
        sort_mileage_asc: "გარბენი ნაკლები",

        btn_search: "ძიება",
        btn_searching: "ვეძებ...",
        empty_state: "ძიების შედეგი აქ გამოჩნდება",
        results_count: "{n} შედეგი",
        results_remaining: "ამ საათში დარჩა {n} ცდა",
        no_results: "ვერაფერი ვიპოვე",

        notice_slow: "ხანდახან 10-15 წამი ჭირდება ინფორმაციის მოძიებას. გთხოვთ მოითმინეთ.",

        err_fetch: "შეცდომა: {msg}",
        err_too_generic:
            "გთხოვთ დააკონკრეტოთ ინფორმაცია უკეთესი ძიებისთვის — დაამატე წელი, " +
            "ქალაქი ან მოდელის ვერსია (მაგ. Toyota Camry 2020 თბილისი).",

        spec_year: "წელი",
        spec_mileage: "გარბენი",
        spec_engine: "ძრავა",
        spec_fuel: "საწვავი",
        spec_gearbox: "კოლოფი",
        spec_drive: "წამყვანი",
        spec_color: "ფერი",
        spec_steering: "საჭე",

        cleared: "განბაჟებული",
        not_cleared: "განუბაჟებელი",
        seller_phone: "ტელეფონი",

        section_description: "აღწერა",
        section_vin: "VIN",
        section_phone: "ტელეფონი",

        posted_on: "გამოქვეყნდა: {date}",
        scraped_on_label: "ინფორმაცია მოვაგროვეთ:",
        scraped_on_note:
            "ვერ მოვიძიეთ ინფორმაცია როდის გამოქვეყნდა, მაგრამ ეს ინფორმაცია მივიღეთ {date}-ს.",

        photo_counter: "{i} / {n}",
        no_photos: "ფოტო არ არის",

        footer_about: "მონაცემები autopapa.ge და myauto.ge-დან. ღია წყაროები. უფასო.",
        footer_contact: "კონტაქტი:",
    },
    en: {
        brand_name: "Car-DB",
        brand_sub: "Georgian car listings",
        nav_listings_count: "{n} listings",

        hero_title: "One search. Every listing.",
        hero_desc:
            "A combined index of autopapa.ge and myauto.ge — searchable " +
            "by VIN, phone number, or a specific description.",

        ph_query: "VIN, phone, brand, model, year, city...",

        filters_toggle: "Filters",
        filter_year:    "Year",
        filter_price:   "Price (USD)",
        filter_mileage: "Mileage (km)",
        filter_from:    "from",
        filter_to:      "to",
        filter_sort:    "Sort",
        filter_clear:   "Clear filters",

        sort_newest:      "Newest first",
        sort_price_asc:   "Cheapest first",
        sort_price_desc:  "Most expensive",
        sort_year_desc:   "Newest year",
        sort_year_asc:    "Oldest year",
        sort_mileage_asc: "Lowest mileage",

        btn_search: "Search",
        btn_searching: "Searching...",
        empty_state: "Search results will appear here",
        results_count: "{n} results",
        results_remaining: "{n} searches left this hour",
        no_results: "Nothing found",

        notice_slow: "Searches can take 10-15 seconds. Please be patient.",

        err_fetch: "Error: {msg}",
        err_too_generic:
            "Please be more specific — add the year, city, or trim " +
            "(e.g. Toyota Camry 2020 Tbilisi).",

        spec_year: "Year",
        spec_mileage: "Mileage",
        spec_engine: "Engine",
        spec_fuel: "Fuel",
        spec_gearbox: "Gearbox",
        spec_drive: "Drive",
        spec_color: "Color",
        spec_steering: "Steering",

        cleared: "Customs cleared",
        not_cleared: "Not cleared",
        seller_phone: "Phone",

        section_description: "Description",
        section_vin: "VIN",
        section_phone: "Phone",

        posted_on: "Posted: {date}",
        scraped_on_label: "Scraped:",
        scraped_on_note:
            "Original posting date is unknown. We collected this information on {date}.",

        photo_counter: "{i} / {n}",
        no_photos: "no photo",

        footer_about: "Data from autopapa.ge and myauto.ge. Open sources. Free.",
        footer_contact: "Contact:",
    },
};

const LANG_KEY = "cardb_lang";
const DEFAULT_LANG = "ka";

function getLang() {
    return localStorage.getItem(LANG_KEY) || DEFAULT_LANG;
}

function setLang(lang) {
    localStorage.setItem(LANG_KEY, lang);
    applyTranslations();
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

    document.querySelectorAll("[data-i18n]").forEach((el) => {
        el.textContent = t(el.dataset.i18n);
    });
    document.querySelectorAll("[data-i18n-html]").forEach((el) => {
        el.innerHTML = t(el.dataset.i18nHtml);
    });
    document.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
        el.placeholder = t(el.dataset.i18nPlaceholder);
    });

    document.querySelectorAll(".lang-btn").forEach((btn) => {
        const active = btn.dataset.lang === lang;
        btn.classList.toggle("is-active", active);
    });
}

document.addEventListener("DOMContentLoaded", applyTranslations);

window.t = t;
window.getLang = getLang;
window.setLang = setLang;
