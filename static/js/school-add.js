/* Dashboard "Add a school": as the name is typed, list the schools already in the chosen
   upazila (verified and pending), like the public form's typeahead. Picking one opens that
   school instead of adding a duplicate; the server re-checks on submit. */
(function () {
  "use strict";
  const form = document.getElementById("addSchool");
  if (!form) return;
  const upazila = document.getElementById("id_upazila"), nameIn = document.getElementById("id_name");
  const list = document.getElementById("schoolList"), schoolUrl = form.dataset.schoolUrl;
  let items = [], active = -1, timer = null, seq = 0;

  function closeList() { list.hidden = true; nameIn.setAttribute("aria-expanded", "false"); active = -1; }
  function render() {
    const q = nameIn.value.trim();
    list.replaceChildren();
    if (items.length) {
      const head = document.createElement("li");
      head.className = "head"; head.setAttribute("role", "presentation");
      head.textContent = "Already listed in this upazila — open it instead of adding";
      list.append(head);
    }
    items.forEach((s, i) => {
      const li = document.createElement("li");
      li.id = `opt${i}`; li.dataset.i = i; li.setAttribute("role", "option"); li.setAttribute("aria-selected", String(i === active));
      const name = document.createElement("span"); name.textContent = s.name; li.append(name);
      if (!s.verified) { const t = document.createElement("span"); t.className = "tag"; t.textContent = "pending"; li.append(t); }
      list.append(li);
    });
    const add = document.createElement("li");
    add.id = `opt${items.length}`; add.dataset.i = items.length; add.className = "add";
    add.setAttribute("role", "option"); add.setAttribute("aria-selected", String(active === items.length));
    add.textContent = items.length ? `Not in the list? Add “${q}” as a new school` : `No match in this upazila. Add “${q}” as a new school`;
    list.append(add);
    list.hidden = !q;
    nameIn.setAttribute("aria-expanded", String(!list.hidden));
    nameIn.setAttribute("aria-activedescendant", active >= 0 ? `opt${active}` : "");
  }
  function choose(i) {
    if (i < items.length) { window.location.href = schoolUrl.replace(/0\/$/, `${items[i].id}/`); return; }
    closeList();
  }
  // A changed name or upazila makes an earlier "similar schools" warning stale.
  function clearWarning() {
    const box = document.getElementById("similarBox");
    if (box) { box.remove(); document.getElementById("addBtn").hidden = false; }
  }
  function syncEnabled() {
    nameIn.disabled = !upazila.value;
    nameIn.placeholder = upazila.value ? "Type the name in English" : "Choose an upazila first";
  }

  nameIn.addEventListener("input", () => {
    clearWarning();
    clearTimeout(timer);
    const q = nameIn.value.trim();
    if (!q || !upazila.value) { items = []; closeList(); return; }
    timer = setTimeout(async () => {
      const mine = ++seq;
      try {
        const r = await fetch(`/api/reference/schools/?upazila=${encodeURIComponent(upazila.value)}&q=${encodeURIComponent(q)}&pending=1`,
                              { headers: { Accept: "application/json" }, credentials: "same-origin" });
        const data = r.ok ? await r.json() : { schools: [] };
        if (mine !== seq || nameIn.value.trim() !== q) return;
        items = data.schools; active = -1; render();
      } catch (_) { /* suggestions only; the server still checks on submit */ }
    }, 220);
  });
  nameIn.addEventListener("keydown", (e) => {
    if (list.hidden) return;
    if (e.key === "ArrowDown") { active = Math.min(items.length, active + 1); render(); e.preventDefault(); }
    else if (e.key === "ArrowUp") { active = Math.max(0, active - 1); render(); e.preventDefault(); }
    else if (e.key === "Enter" && active >= 0) { choose(active); e.preventDefault(); }
    else if (e.key === "Escape") closeList();
  });
  list.addEventListener("mousedown", (e) => {
    const li = e.target.closest("li[role=option]");
    if (li) { e.preventDefault(); choose(Number(li.dataset.i)); }
  });
  nameIn.addEventListener("blur", () => setTimeout(closeList, 120));
  upazila.addEventListener("change", () => { clearWarning(); items = []; closeList(); syncEnabled(); });
  // The upazila list reloads (cascade.js), so no upazila is chosen until the user picks one.
  document.getElementById("id_district").addEventListener("change", () => {
    clearWarning(); items = []; closeList(); nameIn.disabled = true; nameIn.placeholder = "Choose an upazila first";
  });
  syncEnabled();
})();
