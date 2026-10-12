/* Searchable picker for long <select>s (district, thana, school): <select data-picker>.
   Tapping the field opens a full-screen sheet on phones (a panel under the field on wider screens)
   with a search box: type a few letters in English or Bangla and the list narrows. The <select>
   stays in the page as the real field (its value is what the form sends, and choosing fires its
   "change" event), so the code that fills and reads it doesn't change. Options written
   "English · বাংলা" show the Bangla on the right. Texts: data-picker-title / -search / -empty /
   -close on the select. Without JavaScript the plain select is used.
   window.WSPicker.sync(select): call after setting select.value from code. */
(function () {
  "use strict";
  const MOBILE = window.matchMedia("(max-width: 640px)");
  const BN_DIGITS = "০১২৩৪৫৬৭৮৯";
  const norm = (s) => (s || "").toLowerCase().replace(/[০-৯]/g, (d) => String(BN_DIGITS.indexOf(d)))
    .replace(/[\s.,'’()\-]+/g, "");
  const pickers = new WeakMap();
  let uid = 0;

  function labelFor(select) {
    const l = select.id && document.querySelector(`label[for="${CSS.escape(select.id)}"]`);
    return l || null;
  }

  function split(text) {
    const i = text.indexOf(" · ");
    return i < 0 ? [text, ""] : [text.slice(0, i), text.slice(i + 3)];
  }

  function el(tag, attrs, ...kids) {
    const n = document.createElement(tag);
    Object.entries(attrs || {}).forEach(([k, v]) => {
      if (k === "class") n.className = v; else if (v !== undefined && v !== null && v !== false) n.setAttribute(k, v === true ? "" : v);
    });
    kids.flat().forEach((k) => n.append(k instanceof Node ? k : document.createTextNode(k)));
    return n;
  }

  function enhance(select) {
    if (pickers.has(select)) return pickers.get(select);
    const id = ++uid, label = labelFor(select);
    const title = select.dataset.pickerTitle || (label ? label.textContent.trim() : select.getAttribute("aria-label") || "");
    const trigger = el("button", { type: "button", class: "picker-trigger", "aria-haspopup": "dialog",
      "aria-expanded": "false", id: `${select.id || "picker" + id}-picker` });
    const triggerText = el("span", { class: "picker-value" });
    trigger.append(triggerText, el("span", { class: "picker-caret", "aria-hidden": "true" }));
    if (label) { label.htmlFor = trigger.id; }
    else if (select.getAttribute("aria-label")) trigger.setAttribute("aria-label", select.getAttribute("aria-label"));
    select.classList.add("picker-native");
    select.tabIndex = -1;
    select.setAttribute("aria-hidden", "true");
    select.after(trigger);

    const listId = `pickerList${id}`;
    const search = el("input", { type: "search", class: "picker-search", role: "combobox", "aria-expanded": "true",
      "aria-controls": listId, "aria-autocomplete": "list", autocomplete: "off", spellcheck: "false",
      placeholder: select.dataset.pickerSearch || "Type to search", "aria-label": select.dataset.pickerSearch || "Type to search" });
    const list = el("ul", { class: "picker-list", role: "listbox", id: listId, "aria-label": title });
    const empty = el("p", { class: "picker-empty", hidden: true }, select.dataset.pickerEmpty || "No match.");
    const close = el("button", { type: "button", class: "picker-close", "aria-label": select.dataset.pickerClose || "Close" }, "✕");
    const dialog = el("div", { class: "picker-dialog", role: "dialog", "aria-modal": "false", "aria-label": title, hidden: true },
      el("div", { class: "picker-head" }, el("p", { class: "picker-title" }, title), close),
      search, list, empty);
    document.body.append(dialog);

    let rows = [], active = -1, open = false;

    function sync() {
      const opt = select.selectedOptions[0];
      const [en, bn] = split(opt ? opt.textContent : "");
      triggerText.replaceChildren(en, bn ? el("span", { class: "picker-bn", lang: "bn" }, bn) : "");
      trigger.classList.toggle("placeholder", !select.value);
      trigger.disabled = select.disabled;
      trigger.setAttribute("aria-invalid", select.getAttribute("aria-invalid") || "false");  // error styling
      if (open && select.disabled) hide(false);
    }

    function build(q) {
      const nq = norm(q);
      list.replaceChildren();
      rows = [];
      const groups = [];
      [...select.children].forEach((node) => {
        if (node.tagName === "OPTGROUP") groups.push([node.label, [...node.children]]);
        else if (node.tagName === "OPTION") {
          if (groups.length && groups[groups.length - 1][0] === null) groups[groups.length - 1][1].push(node);
          else groups.push([null, [node]]);
        }
      });
      groups.forEach(([heading, options]) => {
        let matches = options.filter((o) => o.value !== "" && !o.disabled).map((o) => {
          const [en, bn] = split(o.textContent), hay = norm(o.textContent);
          if (nq && !hay.includes(nq)) return null;
          const starts = !nq || [en, bn, ...en.split(/\s+/)].some((w) => norm(w).startsWith(nq));
          return { o, en, bn, rank: starts ? 0 : 1 };
        }).filter(Boolean);
        if (nq) matches.sort((a, b) => a.rank - b.rank);
        if (!matches.length) return;
        if (heading) list.append(el("li", { class: "picker-group", role: "presentation" }, heading));
        matches.forEach((m) => {
          const i = rows.length;
          const li = el("li", { role: "option", id: `${listId}-${i}`, class: "picker-row",
            "aria-selected": String(m.o.value === select.value) },
            el("span", { class: "picker-en" }, m.en), m.bn ? el("span", { class: "picker-bn", lang: "bn" }, m.bn) : "");
          li.addEventListener("click", () => choose(i));
          rows.push({ li, value: m.o.value });
          list.append(li);
        });
      });
      empty.hidden = rows.length > 0;
      setActive(nq ? 0 : rows.findIndex((r) => r.value === select.value));
    }

    function setActive(i) {
      active = rows.length ? Math.max(-1, Math.min(i, rows.length - 1)) : -1;
      rows.forEach((r, j) => r.li.classList.toggle("active", j === active));
      search.setAttribute("aria-activedescendant", active >= 0 ? rows[active].li.id : "");
      if (active >= 0) rows[active].li.scrollIntoView({ block: "nearest" });
    }

    function choose(i) {
      const r = rows[i];
      if (!r) return;
      const changed = select.value !== r.value;
      select.value = r.value;
      sync();
      hide(true);
      if (changed) select.dispatchEvent(new Event("change", { bubbles: true }));
    }

    function place() {
      if (MOBILE.matches) { dialog.style.cssText = ""; return; }
      const r = trigger.getBoundingClientRect();
      const below = window.innerHeight - r.bottom;
      dialog.style.left = `${Math.max(8, Math.min(r.left, window.innerWidth - Math.max(r.width, 280) - 8))}px`;
      dialog.style.width = `${Math.max(r.width, 280)}px`;
      if (below < 260 && r.top > below) { dialog.style.top = ""; dialog.style.bottom = `${window.innerHeight - r.top + 4}px`; }
      else { dialog.style.bottom = ""; dialog.style.top = `${r.bottom + 4}px`; }
    }

    function show() {
      if (select.disabled || open) return;
      open = true;
      search.value = "";
      build("");
      dialog.hidden = false;
      dialog.classList.toggle("sheet", MOBILE.matches);
      dialog.setAttribute("aria-modal", String(MOBILE.matches));
      document.documentElement.classList.toggle("picker-locked", MOBILE.matches);
      trigger.setAttribute("aria-expanded", "true");
      place();
      search.focus({ preventScroll: true });
      if (active >= 0) rows[active].li.scrollIntoView({ block: "center" });
    }

    function hide(focusTrigger) {
      if (!open) return;
      open = false;
      dialog.hidden = true;
      document.documentElement.classList.remove("picker-locked");
      trigger.setAttribute("aria-expanded", "false");
      if (focusTrigger) trigger.focus();
    }

    trigger.addEventListener("click", () => (open ? hide(true) : show()));
    trigger.addEventListener("keydown", (e) => {
      if (["ArrowDown", "ArrowUp", "Enter", " "].includes(e.key)) { e.preventDefault(); show(); }
    });
    close.addEventListener("click", () => hide(true));
    search.addEventListener("input", () => build(search.value));
    dialog.addEventListener("keydown", (e) => {
      if (e.key === "Escape") { e.preventDefault(); hide(true); }
      else if (e.key === "ArrowDown") { e.preventDefault(); setActive(active + 1); }
      else if (e.key === "ArrowUp") { e.preventDefault(); setActive(active - 1); }
      else if (e.key === "Enter" && e.target === search) { e.preventDefault(); choose(active >= 0 ? active : 0); }
      else if (e.key === "Tab" && dialog.classList.contains("sheet")) {  // stay inside the sheet
        const f = [search, close];
        const i = f.indexOf(document.activeElement);
        e.preventDefault();
        f[(i + (e.shiftKey ? f.length - 1 : 1)) % f.length].focus();
      }
    });
    document.addEventListener("mousedown", (e) => {
      if (open && !dialog.contains(e.target) && !trigger.contains(e.target)) hide(false);
    });
    window.addEventListener("resize", () => { if (open) { dialog.classList.toggle("sheet", MOBILE.matches); place(); } });
    window.addEventListener("scroll", () => { if (open && !MOBILE.matches) place(); }, true);
    select.addEventListener("change", sync);
    select.addEventListener("focus", () => trigger.focus());  // e.g. "focus the first error" in register.js
    new MutationObserver(sync).observe(select, { childList: true, subtree: true, attributes: true,
      attributeFilter: ["disabled", "aria-invalid"] });
    sync();
    const api = { sync, show, hide, trigger };
    pickers.set(select, api);
    return api;
  }

  window.WSPicker = {
    enhance,
    sync(select) { const p = pickers.get(select); if (p) p.sync(); },
  };
  document.querySelectorAll("select[data-picker]").forEach(enhance);
})();
