/* Dashboard student editor: district → upazila/area → school cascade (Add school: district → upazila/area).
   Areas are grouped like the public form (city-corporation thanas, cantonments, upazilas, "Other area").
   Uses the same reference API as the public form, so region/district data
   always comes from the database. */
(function () {
  "use strict";
  const district = document.querySelector('[data-cascade="district"]');
  const upazila = document.querySelector('[data-cascade="upazila"]');
  const school = document.querySelector('[data-cascade="school"]');
  if (!district || !upazila) return;

  // items: [{id, text, group?}]; consecutive items with the same group go in one <optgroup>.
  function fill(select, items, label) {
    select.replaceChildren();
    if (!items.length) {
      const o = new Option(`No ${label} found`, "");
      o.disabled = true; o.selected = true;
      select.add(o);
      return;
    }
    select.add(new Option(`Choose ${label}…`, "", true, true));
    let group = null;
    items.forEach((it) => {
      if (it.group && (!group || group.label !== it.group)) {
        group = document.createElement("optgroup");
        group.label = it.group;
        select.append(group);
      }
      (it.group ? group : select).append(new Option(it.text, it.id));
    });
  }

  async function getJSON(url) {
    const r = await fetch(url, { headers: { Accept: "application/json" }, credentials: "same-origin" });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return r.json();
  }

  async function loadSchools() {
    if (!school) return;
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
      fill(upazila, data.upazilas.map((u) => ({ id: u.id, text: u.name, group: u.group })), "upazila or area");
    } catch (e) {
      fill(upazila, [], "upazila or area");
    } finally { upazila.disabled = false; }
    if (school) fill(school, [], "school");
  }

  district.addEventListener("change", loadUpazilas);
  upazila.addEventListener("change", loadSchools);
})();
