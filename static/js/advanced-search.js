/* Dashboard advanced search: a query builder for the Students and Schools lists.
   Groups of conditions (field → operator → value); each group matches ALL or ANY of its conditions,
   and the groups are combined with ALL or ANY. The query travels as JSON in the hidden `adv` input,
   which belongs to the page's filter form (form="…"), so the other filters are kept. The server
   checks every field, operator and value again (apps/dashboard/advanced.py). */
(function () {
  "use strict";
  const root = document.getElementById("advBuilder");
  const input = document.getElementById("advInput");
  if (!root || !input) return;
  const meta = JSON.parse(document.getElementById("advMeta").textContent);
  const fields = Object.fromEntries(meta.fields.map((f) => [f.key, f]));
  const form = document.getElementById(input.getAttribute("form"));
  let query = JSON.parse(document.getElementById("advQuery").textContent || "{}");
  if (!query || !Array.isArray(query.groups) || !query.groups.length) {
    query = { match: "all", groups: [newGroup()] };
  }

  function newGroup() { return { match: "all", conditions: [newCondition()] }; }
  function newCondition() {
    const f = meta.fields[0];
    return { field: f.key, op: f.ops[0].key, value: defaultValue(f, f.ops[0]) };
  }
  function defaultValue(f, op) {
    if (op.takes === "list") return [];
    if (op.takes === "two") return ["", ""];
    return op.takes === "none" ? undefined : "";
  }
  function el(tag, attrs, ...kids) {
    const n = document.createElement(tag);
    Object.entries(attrs || {}).forEach(([k, v]) => {
      if (k === "class") n.className = v; else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
      else if (v !== undefined && v !== null && v !== false) n.setAttribute(k, v === true ? "" : v);
    });
    kids.flat().forEach((k) => n.append(k instanceof Node ? k : document.createTextNode(k)));
    return n;
  }
  function matchSelect(value, onchange, label) {
    const s = el("select", { "aria-label": label, onchange: (e) => onchange(e.target.value) },
      el("option", { value: "all" }, "ALL"), el("option", { value: "any" }, "ANY"));
    s.value = value === "any" ? "any" : "all";
    return s;
  }

  function fieldSelect(c) {
    const s = el("select", { "aria-label": "Field", class: "adv-field" });
    let group = null;
    meta.fields.forEach((f) => {
      if (!group || group.label !== f.group) { group = el("optgroup", { label: f.group }); s.append(group); }
      group.append(el("option", { value: f.key }, f.label));
    });
    s.value = c.field;
    s.addEventListener("change", () => {
      const f = fields[s.value];
      c.field = f.key; c.op = f.ops[0].key; c.value = defaultValue(f, f.ops[0]);
      render();
    });
    return s;
  }

  function opSelect(c, f) {
    const s = el("select", { "aria-label": "Condition", class: "adv-op" },
      f.ops.map((o) => el("option", { value: o.key }, o.label)));
    s.value = c.op;
    s.addEventListener("change", () => {
      const before = f.ops.find((o) => o.key === c.op), after = f.ops.find((o) => o.key === s.value);
      c.op = s.value;
      if (!before || before.takes !== after.takes) c.value = defaultValue(f, after);
      render();
    });
    return s;
  }

  function valueInput(f, value, set, label) {
    const attrs = { "aria-label": label, value: value ?? "", oninput: (e) => set(e.target.value) };
    if (f.type === "number") return el("input", { ...attrs, type: "number", inputmode: "numeric", class: "adv-num" });
    if (f.type === "date") {
      const i = el("input", { ...attrs, type: "text", placeholder: "dd/mm/yyyy", "data-datefield": true, class: "adv-date" });
      i.addEventListener("change", (e) => set(e.target.value));
      return i;
    }
    return el("input", { ...attrs, type: "text", maxlength: 200, class: "adv-text" });
  }

  function valueWidget(c, f) {
    const op = f.ops.find((o) => o.key === c.op) || f.ops[0];
    if (op.takes === "none") return [];
    if (op.takes === "list") {
      const chosen = new Set((Array.isArray(c.value) ? c.value : []).map(String));
      const s = el("select", { multiple: true, "aria-label": `${f.label}: choose one or more`, class: "adv-list",
        size: Math.min(6, Math.max(3, f.choices.length)) },
        f.choices.map(([v, l]) => el("option", { value: v, selected: chosen.has(String(v)) }, l || "(blank)")));
      s.addEventListener("change", () => { c.value = [...s.selectedOptions].map((o) => o.value); });
      return [s];
    }
    if (op.takes === "two") {
      const v = Array.isArray(c.value) ? c.value : ["", ""];
      c.value = v;
      return [valueInput(f, v[0], (x) => { v[0] = x; }, `${f.label}: from`), el("span", { class: "muted" }, "and"),
              valueInput(f, v[1], (x) => { v[1] = x; }, `${f.label}: to`)];
    }
    return [valueInput(f, c.value, (x) => { c.value = x; }, `${f.label}: value`)];
  }

  function render() {
    root.replaceChildren();
    if (query.groups.length > 1) {
      root.append(el("p", { class: "adv-top" }, "Match ",
        matchSelect(query.match, (v) => { query.match = v; }, "Combine the groups with"), " of these groups:"));
    }
    query.groups.forEach((g, gi) => {
      const box = el("fieldset", { class: "adv-group" },
        el("legend", {}, `Group ${gi + 1}`),
        el("p", { class: "adv-match" }, "Match ", matchSelect(g.match, (v) => { g.match = v; }, `Group ${gi + 1} matches`),
          " of these conditions:"));
      g.conditions.forEach((c, ci) => {
        const f = fields[c.field] || meta.fields[0];
        box.append(el("div", { class: "adv-cond" }, fieldSelect(c), opSelect(c, f), valueWidget(c, f),
          el("button", { type: "button", class: "btn small", "aria-label": "Remove this condition",
            onclick: () => { g.conditions.splice(ci, 1); if (!g.conditions.length) query.groups.splice(gi, 1);
              if (!query.groups.length) query.groups.push(newGroup()); render(); } }, "×")));
      });
      box.append(el("div", { class: "row" },
        el("button", { type: "button", class: "btn small", onclick: () => { g.conditions.push(newCondition()); render(); } },
          "+ Condition"),
        query.groups.length > 1 ? el("button", { type: "button", class: "link",
          onclick: () => { query.groups.splice(gi, 1); render(); } }, "Remove group") : ""));
      root.append(box);
    });
    root.querySelectorAll("input[data-datefield]").forEach((i) => window.WSDate && window.WSDate.enhance(i));
  }

  // Conditions still missing their value are left out rather than sent half-filled.
  function serialize() {
    const groups = query.groups.map((g) => ({
      match: g.match,
      conditions: g.conditions.filter((c) => {
        const f = fields[c.field], op = f && f.ops.find((o) => o.key === c.op);
        if (!op) return false;
        if (op.takes === "none") return true;
        if (op.takes === "list") return Array.isArray(c.value) && c.value.length;
        if (op.takes === "two") return Array.isArray(c.value) && c.value.every((v) => String(v).trim());
        return String(c.value ?? "").trim() !== "";
      }).map((c) => (fields[c.field].ops.find((o) => o.key === c.op).takes === "none"
        ? { field: c.field, op: c.op } : { field: c.field, op: c.op, value: c.value })),
    })).filter((g) => g.conditions.length);
    input.value = groups.length ? JSON.stringify({ match: query.match, groups }) : "";
  }

  document.getElementById("advAddGroup")?.addEventListener("click", () => { query.groups.push(newGroup()); render(); });
  document.getElementById("advRun")?.addEventListener("click", () => {
    serialize();
    if (form) form.requestSubmit ? form.requestSubmit() : form.submit();
  });
  if (form) form.addEventListener("submit", serialize);
  window.WSAdvanced = { serialize, get query() { return query; } };  // saved searches read the current query
  render();
})();
