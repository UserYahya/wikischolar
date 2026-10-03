/* WikiScholar registration form.
   All reference data (districts, regions, upazilas, schools) is fetched from
   the API; nothing about the district→region mapping lives in this file.
   Answers are kept as a draft in sessionStorage (this tab only) and each step is a
   browser history entry, so Back — the form's or the browser's — never loses data. */
(() => {
  "use strict";
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const form = $("#regForm");
  const csrf = () => (document.cookie.match(/csrftoken=([^;]+)/) || [])[1] || $("[name=csrfmiddlewaretoken]").value;
  const en = (s) => String(s).replace(/[০-৯]/g, (d) => "০১২৩৪৫৬৭৮৯".indexOf(d));
  // Must match apps/registration/validators.py (_ENGLISH)
  const ENGLISH = /^[A-Za-z0-9 .,'()&/-]*$/;
  const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;

  const MSG = {
    required: "This field is required.",
    choose: "Please choose one.",
    english: "Please write this in English (A-Z letters and 0-9 digits only).",
    phone: "Enter a valid Bangladeshi mobile number (for example 01712345678).",
    email: "Enter a valid email address.",
    dob: "Date of birth must be in the past.",
    dobFormat: "Enter the date as dd/mm/yyyy, for example 14/03/2012.",
    rollOrSid: "Fill in either the class roll or the student ID.",
    relationOther: "Write the student's relation to the guardian.",
    declaration: "Tick the guardian declaration: the form must be filled in by the student's guardian.",
    verify: "Verify your email address to continue.",
    consent: "Agree to the Youth Safety Policy to complete registration.",
    network: "Couldn't reach the server. Check your internet connection and try again.",
    schoolPicked: "School selected from the list.",
    schoolNew: "This will be added as a new school; our team will verify it later.",
  };
  const STEP_FIELDS = {
    1: ["guardian_declaration", "student_name", "date_of_birth", "gender", "guardian_name", "guardian_relation",
        "guardian_relation_other"],
    2: ["district", "upazila", "school_name", "current_class", "class_roll", "student_id_sid"],
    3: ["phone", "email", "email_otp"],
    4: ["policy_consent"],
  };
  const DRAFT_FIELDS = ["guardian_declaration", "student_name", "date_of_birth", "gender", "guardian_name",
    "guardian_relation", "guardian_relation_other", "district", "upazila", "current_class", "school_name", "school_id",
    "class_roll", "student_id_sid", "phone", "email", "policy_consent", "updates_opt_in"];
  const DRAFT_KEY = "ws_registration_draft_v1";
  const state = { step: 1, verificationId: null, verifiedEmail: null, districts: new Map(), typoConfirmed: false,
                  done: false, restoring: false };

  async function api(url, body) {
    const opts = body === undefined ? {} : {
      method: "POST", body: JSON.stringify(body),
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() },
    };
    const res = await fetch(url, { credentials: "same-origin", ...opts });
    let data = {};
    try { data = await res.json(); } catch (_) { /* empty */ }
    return { ok: res.ok, status: res.status, data };
  }

  // ---------- errors ----------
  function setError(name, msg) {
    const el = $(`[data-err="${name}"]`);
    if (el) el.textContent = msg || "";
    $$(`[name="${name}"]`).forEach((i) => i.type !== "radio" ? i.setAttribute("aria-invalid", msg ? "true" : "false") : null);
  }
  const clearErrors = (names) => names.forEach((n) => setError(n, ""));

  const val = (name) => {
    const els = $$(`[name="${name}"]`);
    if (!els.length) return "";
    if (els[0].type === "radio") return (els.find((e) => e.checked) || {}).value || "";
    if (els[0].type === "checkbox") return els[0].checked;
    return els[0].value.trim();
  };

  // ---------- draft (survives Back, reload and leaving/returning in this tab) ----------
  function saveDraft() {
    if (state.restoring || state.done) return;
    const data = { step: state.step, verificationId: state.verificationId, verifiedEmail: state.verifiedEmail,
                   typoConfirmed: state.typoConfirmed, fields: {} };
    DRAFT_FIELDS.forEach((n) => { data.fields[n] = val(n); });
    try { sessionStorage.setItem(DRAFT_KEY, JSON.stringify(data)); } catch (_) { /* storage off: no draft */ }
  }
  function loadDraft() {
    try { return JSON.parse(sessionStorage.getItem(DRAFT_KEY) || "null"); } catch (_) { return null; }
  }
  function clearDraft() { try { sessionStorage.removeItem(DRAFT_KEY); } catch (_) { /* ignore */ } }
  function setField(name, v) {
    const els = $$(`[name="${name}"]`);
    if (!els.length || v === undefined || v === null) return;
    if (els[0].type === "radio") els.forEach((e) => { e.checked = e.value === v; });
    else if (els[0].type === "checkbox") els[0].checked = !!v;
    else els[0].value = v;
  }

  // ---------- step navigation (each step is a history entry) ----------
  function showStep(n, { push = true, focus = true } = {}) {
    state.step = n;
    $$(".step").forEach((s) => (s.hidden = Number(s.dataset.step) !== n));
    $$("[data-step-tab]").forEach((li) => {
      const k = Number(li.dataset.stepTab);
      li.toggleAttribute("aria-current", k === n);
      if (k === n) li.setAttribute("aria-current", "step");
      li.classList.toggle("complete", k < n);
      $(".n", li).textContent = k < n ? "✓" : String(k);
      // finished steps can be reopened by clicking them
      if (k < n) { li.setAttribute("role", "button"); li.tabIndex = 0; li.title = "Go back to this step"; }
      else { li.removeAttribute("role"); li.removeAttribute("tabindex"); li.removeAttribute("title"); }
    });
    $("#back").hidden = n === 1;
    $("#next").hidden = n === 4;
    $("#submit").hidden = n !== 4;
    updateSubmit();
    if (push && (history.state || {}).wsStep !== n) history.pushState({ wsStep: n }, "", `#step-${n}`);
    saveDraft();
    if (!focus) return;
    const h = $(`.step[data-step="${n}"] h2`);
    h.setAttribute("tabindex", "-1");
    h.focus({ preventScroll: true });
    form.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" });
  }

  function validateStep(n) {
    clearErrors(STEP_FIELDS[n]);
    let ok = true;
    const fail = (name, msg) => { setError(name, msg); ok = false; };
    for (const name of STEP_FIELDS[n]) {
      const v = val(name);
      if (["guardian_declaration", "class_roll", "student_id_sid", "email_otp", "policy_consent"].includes(name)) continue;
      if (name === "guardian_relation_other" && val("guardian_relation") !== "other") continue;
      if (!v) fail(name, name === "guardian_relation_other" ? MSG.relationOther
        : ["gender", "guardian_relation", "district", "upazila", "current_class"].includes(name) ? MSG.choose : MSG.required);
    }
    STEP_FIELDS[n].forEach((name) => {
      const el = $(`[name="${name}"][data-english]`);
      if (el && el.value && !ENGLISH.test(en(el.value))) fail(name, MSG.english);
    });
    if (n === 1 && !val("guardian_declaration")) fail("guardian_declaration", MSG.declaration);
    if (n === 1 && val("date_of_birth")) {
      const d = window.WSDate.parse(val("date_of_birth"));
      if (!d) fail("date_of_birth", MSG.dobFormat);
      else if (d >= new Date(new Date().toDateString())) fail("date_of_birth", MSG.dob);
    }
    if (n === 2 && !val("class_roll") && !val("student_id_sid")) {
      fail("class_roll", MSG.rollOrSid); fail("student_id_sid", MSG.rollOrSid);
    }
    if (n === 3) {
      const phone = normPhone(val("phone"));
      if (val("phone") && !/^01[3-9]\d{8}$/.test(phone)) fail("phone", MSG.phone);
      if (val("email") && !EMAIL.test(val("email"))) fail("email", MSG.email);
      if (ok && !isVerified()) fail("email_otp", MSG.verify);
    }
    if (!ok) {
      const first = $(`.step[data-step="${n}"] [aria-invalid="true"], .step[data-step="${n}"] .err:not(:empty)`);
      if (first) (first.matches("input,select") ? first : first.closest(".field")?.querySelector("input,select"))?.focus();
    }
    return ok;
  }

  $("#next").addEventListener("click", () => { if (validateStep(state.step)) showStep(state.step + 1); });
  $("#back").addEventListener("click", () => {
    // Walk the history back when this step is the current entry; otherwise just show the previous step.
    if ((history.state || {}).wsStep === state.step && state.step > 1) history.back();
    else showStep(state.step - 1);
  });
  window.addEventListener("popstate", (e) => {
    if (state.done) return;
    const target = (e.state && e.state.wsStep) || 1;
    if (target > state.step) {
      // Browser Forward: only move past steps that are still valid.
      for (let k = state.step; k < target; k += 1) {
        if (!validateStep(k)) { history.replaceState({ wsStep: k }, "", `#step-${k}`); showStep(k, { push: false }); return; }
      }
    }
    showStep(target, { push: false });
  });
  $$("[data-step-tab]").forEach((li) => {
    const go = () => { const k = Number(li.dataset.stepTab); if (k < state.step) showStep(k); };
    li.addEventListener("click", go);
    li.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); } });
  });

  // ---------- English only ----------
  // Bangla digits become 0-9 as you type; any other non-English character is flagged at once.
  $$("[data-english], #phone").forEach((el) => el.addEventListener("input", () => {
    const fixed = en(el.value);
    if (fixed !== el.value) {
      const pos = el.selectionStart;
      el.value = fixed;
      try { el.setSelectionRange(pos, pos); } catch (_) { /* some input types */ }
    }
    if (el.matches("[data-english]")) setError(el.name, ENGLISH.test(el.value) ? "" : MSG.english);
  }));

  // ---------- guardian declaration (required) ----------
  $("#guardian_declaration").addEventListener("change", () => setError("guardian_declaration", ""));

  // ---------- guardian relation: "Other" needs a typed relation ----------
  const relationOther = $("#relationOtherField");
  function syncRelation({ focus = false } = {}) {
    const other = val("guardian_relation") === "other";
    relationOther.hidden = !other;
    if (other && focus) $("#guardian_relation_other").focus();
    if (!other) { $("#guardian_relation_other").value = ""; setError("guardian_relation_other", ""); }
  }
  $$('[name="guardian_relation"]').forEach((r) => r.addEventListener("change", () => {
    setError("guardian_relation", ""); syncRelation({ focus: true });
  }));

  // ---------- district → region, upazila ----------
  const districtSel = $("#district"), upazilaSel = $("#upazila"), regionOut = $("#region");
  async function loadDistricts() {
    const { ok, data } = await api("/api/reference/districts/");
    if (!ok) { districtSel.innerHTML = `<option value="">${MSG.network}</option>`; return; }
    districtSel.innerHTML = `<option value="">Choose a district</option>` +
      data.districts.sort((a, b) => a.name.localeCompare(b.name, "en"))
        .map((d) => { state.districts.set(String(d.id), d); return `<option value="${d.id}">${esc(d.name)}</option>`; }).join("");
  }
  async function loadUpazilas() {
    const d = state.districts.get(districtSel.value);
    regionOut.textContent = d ? (d.region ? d.region.name : "No region assigned") : "Shown after you choose a district";
    regionOut.classList.toggle("empty", !d || !d.region);
    upazilaSel.disabled = true;
    upazilaSel.innerHTML = `<option value="">${d ? "Loading…" : "Choose a district first"}</option>`;
    if (!d) return;
    const { ok, data } = await api(`/api/reference/districts/${d.id}/upazilas/`);
    if (!ok) { upazilaSel.innerHTML = `<option value="">${MSG.network}</option>`; return; }
    upazilaSel.innerHTML = `<option value="">Choose an upazila</option>` +
      data.upazilas.map((u) => `<option value="${u.id}">${esc(u.name)}</option>`).join("");
    upazilaSel.disabled = false;
  }
  districtSel.addEventListener("change", async () => { resetSchool(true); await loadUpazilas(); saveDraft(); });
  upazilaSel.addEventListener("change", () => { resetSchool(!upazilaSel.value); saveDraft(); });

  // ---------- school typeahead ----------
  const schoolIn = $("#school_name"), schoolId = $("#school_id"), list = $("#schoolList"), schoolHint = $("#schoolHint");
  let timer = null, items = [], active = -1, lastQuery = "";
  function resetSchool(disable) {
    schoolIn.value = ""; schoolId.value = ""; schoolHint.textContent = ""; closeList();
    schoolIn.disabled = disable;
    schoolIn.placeholder = disable ? "Choose an upazila first" : "Type the school name in English";
  }
  function closeList() { list.hidden = true; schoolIn.setAttribute("aria-expanded", "false"); active = -1; }
  function render() {
    const q = schoolIn.value.trim();
    list.innerHTML = items.map((s, i) =>
      `<li role="option" id="opt${i}" data-i="${i}" aria-selected="${i === active}">
         <span>${esc(s.name)}</span>${s.verified ? "" : '<span class="tag">being verified</span>'}</li>`).join("") +
      (q ? `<li role="option" class="add" id="opt${items.length}" data-i="${items.length}" aria-selected="${active === items.length}">
             Not in the list? Add it as new: “${esc(q)}”</li>` : "");
    list.hidden = !q && !items.length;
    schoolIn.setAttribute("aria-expanded", String(!list.hidden));
    schoolIn.setAttribute("aria-activedescendant", active >= 0 ? `opt${active}` : "");
  }
  function choose(i) {
    if (i < items.length) {
      schoolId.value = items[i].id;
      schoolIn.value = items[i].name;
      schoolHint.textContent = MSG.schoolPicked;
    } else {
      schoolId.value = "";
      schoolHint.textContent = MSG.schoolNew;
    }
    setError("school_name", ENGLISH.test(schoolIn.value) ? "" : MSG.english);
    closeList();
    saveDraft();
  }
  schoolIn.addEventListener("input", () => {
    schoolId.value = ""; schoolHint.textContent = "";
    clearTimeout(timer);
    const q = schoolIn.value.trim();
    if (!q) { items = []; closeList(); return; }
    timer = setTimeout(async () => {
      lastQuery = q;
      const { ok, data } = await api(`/api/reference/schools/?upazila=${encodeURIComponent(upazilaSel.value)}&q=${encodeURIComponent(q)}`);
      if (q !== lastQuery) return;
      items = ok ? data.schools : [];
      active = -1; render();
    }, 220);
  });
  schoolIn.addEventListener("keydown", (e) => {
    if (list.hidden) return;
    const max = items.length + (schoolIn.value.trim() ? 1 : 0) - 1;
    if (e.key === "ArrowDown") { active = Math.min(max, active + 1); render(); e.preventDefault(); }
    else if (e.key === "ArrowUp") { active = Math.max(0, active - 1); render(); e.preventDefault(); }
    else if (e.key === "Enter" && active >= 0) { choose(active); e.preventDefault(); }
    else if (e.key === "Escape") closeList();
  });
  list.addEventListener("mousedown", (e) => { const li = e.target.closest("li"); if (li) { e.preventDefault(); choose(Number(li.dataset.i)); } });
  schoolIn.addEventListener("blur", () => setTimeout(() => {
    closeList();
    if (schoolIn.value.trim() && !schoolId.value && !schoolHint.textContent) schoolHint.textContent = MSG.schoolNew;
    saveDraft();
  }, 120));

  // ---------- phone ----------
  function normPhone(v) {
    let d = en(v).replace(/\D/g, "");
    if (d.startsWith("880")) d = d.slice(2); else if (d.startsWith("88") && d.length === 13) d = d.slice(2);
    return d;
  }

  // ---------- email: instant typo hint + OTP ----------
  const emailIn = $("#email"), typoBox = $("#typoBox");
  const isVerified = () => state.verificationId && state.verifiedEmail === emailIn.value.trim().toLowerCase();
  let typoTimer = null, typoSeq = 0, sendAfterTypo = false;
  function showTypo(data, { fromSend = false } = {}) {
    $("#typoText").textContent = data.message;
    $("#typoFix").textContent = `Use ${data.suggested_email}`;
    $("#typoFix").dataset.email = data.suggested_email;
    typoBox.hidden = false;
    sendAfterTypo = fromSend;
  }
  async function checkTypo() {
    const email = emailIn.value.trim().toLowerCase();
    if (state.typoConfirmed || !email.includes("@")) { typoBox.hidden = true; return; }
    const seq = ++typoSeq;
    try {
      const { ok, data } = await api(`/api/registration/email/check/?email=${encodeURIComponent(email)}`);
      if (seq !== typoSeq || emailIn.value.trim().toLowerCase() !== email) return;
      if (ok && data.typo_suggestion) showTypo(data); else typoBox.hidden = true;
    } catch (_) { /* hint only; ignore network errors */ }
  }
  emailIn.addEventListener("input", () => {
    typoBox.hidden = true; state.typoConfirmed = false; setError("email", "");
    if (state.verifiedEmail && !isVerified()) {
      $("#verifiedNote").hidden = true; $("#sendOtp").hidden = false; $("#otpEntry").hidden = true;
      state.verificationId = null; state.verifiedEmail = null;
    }
    clearTimeout(typoTimer);
    typoTimer = setTimeout(checkTypo, 700);
    updateSubmit();
  });
  emailIn.addEventListener("blur", () => { clearTimeout(typoTimer); checkTypo(); });

  let cooldown = null;
  function startCooldown(sec = 60) {
    const btn = $("#resendOtp");
    btn.disabled = true;
    clearInterval(cooldown);
    let left = sec;
    btn.textContent = `Send a new code (${left}s)`;
    cooldown = setInterval(() => {
      left -= 1;
      btn.textContent = left > 0 ? `Send a new code (${left}s)` : "Send a new code";
      if (left <= 0) { clearInterval(cooldown); btn.disabled = false; }
    }, 1000);
  }
  async function sendOtp() {
    clearErrors(["email", "email_otp"]);
    const email = emailIn.value.trim().toLowerCase();
    if (!email.includes("@")) { setError("email", MSG.email); emailIn.focus(); return; }
    const btn = $("#sendOtp"); btn.setAttribute("aria-busy", "true"); btn.disabled = true;
    try {
      // The server checks for typos before the address format, so "name@gmailcom" gets a suggestion.
      const { ok, data } = await api("/api/registration/email/send-otp/", { email, confirm_typo: state.typoConfirmed });
      if (data.typo_suggestion) { showTypo(data, { fromSend: true }); return; }
      if (!ok) { setError("email", data.message || MSG.network); return; }
      state.verificationId = data.verification_id;
      $("#otpEntry").hidden = false;
      $("#otpHint").textContent = `We sent a 6-digit code by email to ${email}. It is valid for ${data.expires_in_minutes} minutes. ` +
        "Can't find it? Check your Spam or Junk folder." +
        (data.debug_code ? ` [dev mode: ${data.debug_code}]` : "");
      $("#email_otp").value = ""; $("#email_otp").focus();
      btn.hidden = true;
      startCooldown();
      saveDraft();
    } catch (_) { setError("email", MSG.network); }
    finally { btn.removeAttribute("aria-busy"); btn.disabled = false; }
  }
  $("#sendOtp").addEventListener("click", sendOtp);
  $("#resendOtp").addEventListener("click", sendOtp);
  $("#typoFix").addEventListener("click", (e) => {
    emailIn.value = e.target.dataset.email; typoBox.hidden = true; state.typoConfirmed = true; setError("email", "");
    saveDraft();
    if (sendAfterTypo) sendOtp(); else emailIn.focus();
  });
  $("#typoKeep").addEventListener("click", () => {
    typoBox.hidden = true; state.typoConfirmed = true;
    saveDraft();
    if (sendAfterTypo) sendOtp();
  });
  $("#verifyOtp").addEventListener("click", async () => {
    setError("email_otp", "");
    const code = en($("#email_otp").value).replace(/\D/g, "");
    if (code.length !== 6) { setError("email_otp", "Enter the 6-digit code."); return; }
    const btn = $("#verifyOtp"); btn.setAttribute("aria-busy", "true");
    try {
      const { ok, data } = await api("/api/registration/email/verify-otp/", { verification_id: state.verificationId, code });
      if (!ok) { setError("email_otp", data.message || MSG.network); return; }
      state.verifiedEmail = emailIn.value.trim().toLowerCase();
      showVerified();
      saveDraft();
    } catch (_) { setError("email_otp", MSG.network); }
    finally { btn.removeAttribute("aria-busy"); }
  });
  function showVerified() {
    $("#otpEntry").hidden = true; $("#sendOtp").hidden = true; $("#verifiedNote").hidden = false;
    updateSubmit();
  }
  $("#email_otp").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); $("#verifyOtp").click(); } });

  // ---------- submit ----------
  function updateSubmit() { $("#submit").disabled = !(isVerified() && $("#policy_consent").checked); }
  $("#policy_consent").addEventListener("change", () => { setError("policy_consent", ""); updateSubmit(); });

  form.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && e.target.matches("input:not([type=checkbox])") && state.step < 4 && e.target.id !== "school_name"
        && e.target.id !== "email_otp") {
      e.preventDefault(); $("#next").click();
    }
  });
  // keep the draft current for every plain field
  form.addEventListener("input", saveDraft);
  form.addEventListener("change", saveDraft);

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!$("#policy_consent").checked) { setError("policy_consent", MSG.consent); return; }
    for (const n of [1, 2, 3]) if (!validateStep(n)) { showStep(n); validateStep(n); return; }
    const btn = $("#submit"); btn.disabled = true; btn.setAttribute("aria-busy", "true");
    const payload = {
      guardian_declaration: val("guardian_declaration"),
      student_name: val("student_name"), date_of_birth: val("date_of_birth"), gender: val("gender"),
      guardian_name: val("guardian_name"), guardian_relation: val("guardian_relation"),
      guardian_relation_other: val("guardian_relation") === "other" ? val("guardian_relation_other") : "",
      district: val("district"), upazila: val("upazila"), school_name: val("school_name"),
      school_id: val("school_id") || null, current_class: val("current_class"),
      class_roll: val("class_roll"), student_id_sid: val("student_id_sid"),
      phone: normPhone(val("phone")), email: val("email").toLowerCase(),
      verification_id: state.verificationId, policy_consent: val("policy_consent"),
      updates_opt_in: val("updates_opt_in"), website: val("website"),
    };
    try {
      const { ok, data } = await api("/api/registration/submit/", payload);
      if (ok) return showDone(data.summary);
      if (data.errors) {
        let firstStep = null;
        for (const [field, msgs] of Object.entries(data.errors)) {
          const name = field === "verification_id" ? "email_otp" : field;
          setError(name, msgs[0]);
          const step = Number(Object.keys(STEP_FIELDS).find((k) => STEP_FIELDS[k].includes(name)));
          if (step && (firstStep === null || step < firstStep)) firstStep = step;
        }
        if (firstStep && firstStep !== 4) showStep(firstStep);
      } else {
        $("#formErr").textContent = data.message || MSG.network;
        if (data.error === "email_not_verified") {
          state.verifiedEmail = null; $("#verifiedNote").hidden = true; $("#sendOtp").hidden = false; showStep(3);
        }
      }
    } catch (_) { $("#formErr").textContent = MSG.network; }
    finally { btn.removeAttribute("aria-busy"); updateSubmit(); }
  });

  function showDone(s) {
    state.done = true;
    clearDraft();
    history.replaceState({ wsDone: true }, "", location.pathname);
    $("#reg").classList.add("is-done");
    $("#wsid").textContent = s.wikischolar_id;
    $("#doneEmail").textContent = s.email;
    const rows = [
      ["Filled in by", s.filled_by],
      ["Name", s.student_name], ["Date of birth", s.date_of_birth], ["Gender", s.gender], ["Guardian", s.guardian],
      ["District", s.district], ["Region", s.region || "—"], ["Upazila", s.upazila],
      ["School", s.school + (s.school_pending ? " (being verified)" : "")], ["Class", s.current_class],
      ["Class roll", s.class_roll || "—"], ["Student ID", s.student_id_sid || "—"], ["Mobile", s.phone],
    ];
    $("#summary").innerHTML = rows.map(([k, v]) => `<dt>${k}</dt><dd>${esc(v)}</dd>`).join("");
    const done = $("#done"); done.hidden = false; done.focus();
  }

  function esc(s) { return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }

  // ---------- start: load districts, then bring back any draft ----------
  async function restore(draft) {
    state.restoring = true;
    const f = draft.fields || {};
    ["guardian_declaration", "student_name", "date_of_birth", "gender", "guardian_name", "guardian_relation",
     "guardian_relation_other", "current_class", "class_roll", "student_id_sid", "phone", "email", "policy_consent",
     "updates_opt_in"].forEach((n) => setField(n, f[n]));
    syncRelation();
    if (f.guardian_relation === "other") setField("guardian_relation_other", f.guardian_relation_other);
    if (f.district && state.districts.has(String(f.district))) {
      districtSel.value = f.district;
      await loadUpazilas();
      if (f.upazila) {
        upazilaSel.value = f.upazila;
        if (upazilaSel.value) {
          resetSchool(false);
          schoolIn.value = f.school_name || "";
          schoolId.value = f.school_id || "";
          if (schoolIn.value) schoolHint.textContent = schoolId.value ? MSG.schoolPicked : MSG.schoolNew;
        }
      }
    }
    state.typoConfirmed = !!draft.typoConfirmed;
    if (draft.verificationId && draft.verifiedEmail && draft.verifiedEmail === (f.email || "").toLowerCase()) {
      state.verificationId = draft.verificationId; state.verifiedEmail = draft.verifiedEmail;
      showVerified();
    }
    state.restoring = false;
    // Reopen the furthest step that's still valid, never beyond the saved one.
    let step = 1;
    const target = Math.min(Math.max(Number(draft.step) || 1, 1), 4);
    while (step < target && validateStep(step)) step += 1;
    for (let k = 1; k <= step; k += 1) clearErrors(STEP_FIELDS[k]);
    return step;
  }

  (async () => {
    await loadDistricts();
    const draft = loadDraft();
    const step = draft ? await restore(draft) : 1;
    // Seed history so the browser's Back button walks steps 1..n before leaving the page.
    history.replaceState({ wsStep: 1 }, "", location.pathname);
    for (let k = 2; k <= step; k += 1) history.pushState({ wsStep: k }, "", `#step-${k}`);
    showStep(step, { push: false, focus: step > 1 });
  })();
})();
