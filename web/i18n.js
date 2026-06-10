// ka/en ლექსიკონი — ნაგულისხმევი ka; არჩევანი localStorage-ში ნახულობს.

const TRANSLATIONS = {
    ka: {
        brand_name: "Car-DB",
        brand_sub: "მანქანების ბაზა",
        nav_listings_count: "{n} განცხადება",
        stat_cars: "მანქანა ბაზაში",
        stat_free: "სრულიად უფასო",
        stat_nosignup: "რეგისტრაცია არ სჭირდება",

        hero_title: "ერთი ძიება. ყველა განცხადება.",
        hero_desc:
            "ქართული მანქანების სრული ბაზა — ეძებე VIN-ით, ნომრით " +
            "ან კონკრეტული აღწერით.",

        ph_query: "VIN, ნომერი, ბრენდი, მოდელი, წელი, ქალაქი...",

        filters_toggle: "ფილტრები",
        filter_year:    "წელი",
        filter_price:   "ფასი (USD)",
        filter_mileage: "გარბენი (კმ)",
        filter_from:    "დან",
        filter_to:      "მდე",
        filter_sort:    "სორტირება",
        filter_clear:   "ფილტრების გასუფთავება",
        filter_brand:   "ბრენდი",
        filter_model:   "მოდელი",
        brand_any:      "ყველა ბრენდი",
        model_any:      "ყველა მოდელი",

        sort_default:     "სორტირება",
        sort_price_desc:  "ფასი: კლებადობით",
        sort_price_asc:   "ფასი: ზრდადობით",
        sort_year_desc:   "წელი: ახლები პირველი",
        sort_year_asc:    "წელი: ძველები პირველი",
        sort_mileage_desc:"გარბენი: კლებადობით",
        sort_mileage_asc: "გარბენი: ზრდადობით",

        btn_search: "ძიება",
        btn_searching: "ვეძებ...",
        empty_state: "ძიების შედეგი აქ გამოჩნდება",
        results_count: "{n} შედეგი",
        results_remaining: "ამ საათში დარჩა {n} ცდა",
        page_of: "გვერდი {p} / {n}",
        page_prev: "← წინა",
        page_next: "შემდეგი →",
        no_results: "ვერაფერი ვიპოვე",

        notice_slow: "ხანდახან 10-15 წამი ჭირდება ინფორმაციის მოძიებას. გთხოვთ მოითმინეთ.",

        err_fetch: "შეცდომა: {msg}",
        err_unknown: "დაფიქსირდა შეცდომა, სცადეთ მოგვიანებით.",
        err_query_too_vague:
            "გთხოვთ დააკონკრეტოთ ინფორმაცია უკეთესი ძიებისთვის — დაამატე წელი, " +
            "ქალაქი ან მოდელის ვერსია (მაგ. Toyota Camry 2020 თბილისი).",
        err_query_empty: "გთხოვთ შეიყვანოთ რაიმე ძიებისთვის ან გამოიყენე ფილტრები.",
        err_phone_too_short: "ნომერი მინიმუმ 4 ციფრი უნდა იყოს.",
        err_car_invalid_key: "არასწორი მისამართი.",
        err_car_not_found: "მანქანა ვერ მოიძებნა — ალბათ წაიშალა წყაროდან.",
        err_cooldown: "მოიცადე {wait} წამი შემდეგი ცდისთვის.",
        err_rate_limited:
            "საათობრივი ლიმიტი ({limit} ცდა) ამოწურეთ. შემდეგ საათში სცადეთ " +
            "ან მომწერეთ Instagram-ზე {contact} მეტი ლიმიტისთვის.",

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
        see_more: "ვრცლად",
        see_less: "დაკეცვა",

        posted_on: "გამოქვეყნდა: {date}",
        scraped_on_label: "ინფორმაცია მოვიძიეთ:",
        scraped_on_note: "ეს ინფორმაცია მოვიძიეთ {date}.",

        photo_counter: "{i} / {n}",
        no_photos: "ფოტო არ არის",

        back_to_search:    "← უკან ძიებაში",
        copy_link:         "ბმულის კოპირება",
        link_copied:       "კოპირებულია",
        detail_loading:    "იტვირთება...",
        detail_not_found:  "ეს განცხადება ვერ მოიძებნა — ალბათ წაშლილია წყაროდან.",
        detail_open_source:"ნახე წყაროზე",
        detail_gallery:    "ფოტოები",

        footer_about: "მანქანების განცხადებების არქივი. უფასო.",
        footer_terms: "წესები",
        footer_privacy: "კონფიდენციალურობა",
        footer_contact: "კონტაქტი:",
    },
    en: {
        brand_name: "Car-DB",
        brand_sub: "Georgian car listings",
        nav_listings_count: "{n} listings",
        stat_cars: "cars indexed",
        stat_free: "100% free",
        stat_nosignup: "no sign-up",

        hero_title: "One search. Every listing.",
        hero_desc:
            "A unified index of Georgian car listings — searchable by VIN, " +
            "phone number, or a specific description.",

        ph_query: "VIN, phone, brand, model, year, city...",

        filters_toggle: "Filters",
        filter_year:    "Year",
        filter_price:   "Price (USD)",
        filter_mileage: "Mileage (km)",
        filter_from:    "from",
        filter_to:      "to",
        filter_sort:    "Sort",
        filter_clear:   "Clear filters",
        filter_brand:   "Brand",
        filter_model:   "Model",
        brand_any:      "All brands",
        model_any:      "All models",

        sort_default:     "Sort",
        sort_price_desc:  "Price: high to low",
        sort_price_asc:   "Price: low to high",
        sort_year_desc:   "Year: newest first",
        sort_year_asc:    "Year: oldest first",
        sort_mileage_desc:"Mileage: high to low",
        sort_mileage_asc: "Mileage: low to high",

        btn_search: "Search",
        btn_searching: "Searching...",
        empty_state: "Search results will appear here",
        results_count: "{n} results",
        results_remaining: "{n} searches left this hour",
        page_of: "Page {p} / {n}",
        page_prev: "← Prev",
        page_next: "Next →",
        no_results: "Nothing found",

        notice_slow: "Searches can take 10-15 seconds. Please be patient.",

        err_fetch: "Error: {msg}",
        err_unknown: "Something went wrong, please try again later.",
        err_query_too_vague:
            "Please be more specific — add the year, city, or trim " +
            "(e.g. Toyota Camry 2020 Tbilisi).",
        err_query_empty: "Enter something to search, or use the filters.",
        err_phone_too_short: "Phone number must be at least 4 digits.",
        err_car_invalid_key: "Invalid address.",
        err_car_not_found: "Car not found — it was probably removed from the source.",
        err_cooldown: "Wait {wait}s before searching again.",
        err_rate_limited:
            "Hourly limit reached ({limit} searches). Try next hour, " +
            "or message {contact} on Instagram for a higher limit.",

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
        see_more: "See more",
        see_less: "See less",

        posted_on: "Posted: {date}",
        scraped_on_label: "Retrieved:",
        scraped_on_note: "Information retrieved on {date}.",

        photo_counter: "{i} / {n}",
        no_photos: "no photo",

        back_to_search:    "← Back to search",
        copy_link:         "Copy link",
        link_copied:       "Copied",
        detail_loading:    "Loading...",
        detail_not_found:  "This listing wasn't found — probably removed from the source.",
        detail_open_source:"Open on source",
        detail_gallery:    "Photos",

        footer_about: "Car listings archive. Free.",
        footer_terms: "Terms",
        footer_privacy: "Privacy",
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
