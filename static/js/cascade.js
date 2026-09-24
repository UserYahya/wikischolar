/* Dashboard student editor: district → upazila → school cascade.
   Uses the same reference API as the public form, so region/district data
   always comes from the database. */
(function () {
  "use strict";
  const district = document.querySelector('[data-cascade="district"]');
  const upazila = document.querySelector('[data-cascade="upazila"]');
  const school = document.querySelector('[data-cascade="school"]');
  if (!district || !upazila || !school) return;

  function fill(select, items, label) {
    select.replaceChildren();
    if (!items.length) {
      const o = new Option(`No ${label} found`, "");
      o.disabled = true; o.selected = true;
      select.add(o);
      return;
    }
    select.add(new Option(`Choose ${label}…`, "", true, true));
    items.forEach((it) => select.add(new Option(it.text, it.id)));
  }

  async function getJSON(url) {
    const r = await fetch(url, { headers: { Accept: "application/json" }, credentials: "same-origin" });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return r.json();
  }

  async function loadSchools() {
    school.disabled = true;
    if (!upazila.value) { fill(school, [], "school"); return; }
    try {
      const data = await getJSON(`/api/reference/schools/?upazila=${encodeURIComponent(upazila.value)}&all=1`);
      fill(school, data.schools.map((s) => ({ id: s.id, text: s.name + (s.verified ? "" : " (pending)") })), "school");
    } catch (e) {
      fill(school, [], "school");
    } finally { school.disabled = false; }
  }

  async function loadUpazilas() {
    upazila.disabled = true;
    try {
      const data = await getJSON(`/api/reference/districts/${encodeURIComponent(district.value)}/upazilas/`);
      fill(upazila, data.upazilas.map((u) => ({ id: u.id, text: u.name })), "upazila");
    } catch (e) {
      fill(upazila, [], "upazila");
    } finally { upazila.disabled = false; }
    fill(school, [], "school");
  }

  district.addEventListener("change", loadUpazilas);
  upazila.addEventListener("change", loadSchools);
})();
