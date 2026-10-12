/* British dates (dd/mm/yyyy), the same on every browser and phone.
   Enhances each <input data-datefield>: typing gets the slashes added and Bangla digits turned
   into 0-9, and a calendar button opens Air Datepicker (static/vendor/air-datepicker) as a
   centred popup. The field always submits dd/mm/yyyy text; the server reads it with
   apps.core.utils.parse_date (which also accepts yyyy-mm-dd), so the form works without JS too.
   Optional attributes: data-min / data-max ("today", "yesterday" or dd/mm/yyyy) and
   data-view="years" to open the calendar on the year grid (for birth dates).
   window.WSDate = { parse, format, enhance } for other scripts (register.js, advanced-search.js). */
(() => {
  "use strict";
  const LOCALE = {
    days: ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"],
    daysShort: ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"],
    daysMin: ["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"],
    months: ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
      "November", "December"],
    monthsShort: ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
    today: "Today", clear: "Clear", dateFormat: "dd/MM/yyyy", timeFormat: "HH:mm", firstDay: 1,
  };
  const en = (s) => String(s ?? "").replace(/[০-৯]/g, (d) => "০১২৩৪৫৬৭৮৯".indexOf(d));
  const pad = (n) => String(n).padStart(2, "0");
  const format = (d) => `${pad(d.getDate())}/${pad(d.getMonth() + 1)}/${d.getFullYear()}`;

  /** dd/mm/yyyy (or yyyy-mm-dd) → local Date, or null if it isn't a real date. */
  function parse(raw) {
    const s = en(raw).trim();
    let m = s.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/);
    let d, mo, y;
    if (m) [, d, mo, y] = m;
    else if ((m = s.match(/^(\d{4})-(\d{2})-(\d{2})$/))) [, y, mo, d] = m;
    else return null;
    const date = new Date(+y, +mo - 1, +d);
    return date.getFullYear() === +y && date.getMonth() === +mo - 1 && date.getDate() === +d ? date : null;
  }

  function limit(v) {
    if (!v) return "";
    const today = new Date(new Date().toDateString());
    if (v === "today") return today;
    if (v === "yesterday") return new Date(today.getFullYear(), today.getMonth(), today.getDate() - 1);
    return parse(v) || "";
  }

  // While typing: Bangla digits → 0-9, "." or "-" → "/", and a slash after the day and the month.
  function onType(e) {
    const el = e.target;
    let v = en(el.value).replace(/[.\-\s]/g, "/").replace(/[^\d/]/g, "");
    if (e.inputType && e.inputType.startsWith("insert") && (/^\d{2}$/.test(v) || /^\d{1,2}\/\d{2}$/.test(v))) v += "/";
    if (v !== el.value) el.value = v;
  }

  function enhance(el) {
    el.type = "text";
    el.inputMode = "numeric";
    el.maxLength = 10;
    el.autocomplete = el.autocomplete || "off";
    if (!el.placeholder) el.placeholder = "dd/mm/yyyy";

    const wrap = document.createElement("span");
    wrap.className = "datefield";
    el.replaceWith(wrap);
    wrap.append(el);
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "datefield-btn";
    btn.setAttribute("aria-label", `Choose ${el.getAttribute("aria-label") || "date"} from a calendar`);
    btn.innerHTML = '<svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" focusable="false">'
      + '<rect x="3.5" y="5" width="17" height="15.5" rx="2" fill="none" stroke="currentColor" stroke-width="1.8"/>'
      + '<path d="M3.5 10h17M8 3v4M16 3v4" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>';
    wrap.append(btn);

    // The calendar is tied to a hidden input so the visible field stays free for typing
    // (Air Datepicker makes its own input read-only in its centred, mobile-style popup).
    const anchor = document.createElement("input");
    anchor.type = "hidden";
    wrap.append(anchor);
    const dp = new window.AirDatepicker(anchor, {
      locale: LOCALE, isMobile: true, autoClose: true, keyboardNav: false, showEvent: "ws-never",
      minDate: limit(el.dataset.min), maxDate: limit(el.dataset.max),
      view: el.dataset.view === "years" ? "years" : "days", minView: "days",
      onSelect({ date }) {
        if (!date) return;
        el.value = format(date);
        el.dispatchEvent(new Event("input", { bubbles: true }));
        el.dispatchEvent(new Event("change", { bubbles: true }));
      },
      onHide(done) { if (done) btn.focus(); },
    });
    btn.addEventListener("click", () => {
      const d = parse(el.value);
      if (d) { dp.selectDate(d, { silent: true }); dp.setViewDate(d); }
      else {
        dp.clear({ silent: true });
        // Birth dates: start near a typical student's birth year rather than this decade.
        if (el.dataset.view === "years") dp.setViewDate(new Date(new Date().getFullYear() - 12, 0, 1));
      }
      dp.setCurrentView(d || el.dataset.view !== "years" ? "days" : "years");
      dp.show();
    });
    el.addEventListener("input", onType);
    // Tidy what was typed or pasted: 1/3/2012 → 01/03/2012, 14032012 → 14/03/2012, 2012-03-14 → 14/03/2012.
    el.addEventListener("blur", () => {
      const digits = en(el.value).trim();
      const d = parse(/^\d{8}$/.test(digits) ? `${digits.slice(0, 2)}/${digits.slice(2, 4)}/${digits.slice(4)}` : digits);
      if (d && format(d) !== el.value) {
        el.value = format(d);
        el.dispatchEvent(new Event("change", { bubbles: true }));
      }
    });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && dp.visible) dp.hide(); });
  }

  window.WSDate = { parse, format, enhance };  // enhance: for inputs added later (advanced search)
  document.querySelectorAll("input[data-datefield]").forEach(enhance);
})();
