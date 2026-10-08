# WikiScholar Registration & Database Platform — Complete Roadmap

> **This is the original product specification** the Phase 1 MVP was built from. It is kept as
> the record of intent. Where the built app differs, an **Update** note says so, and
> [Section 10](#10-built-after-the-original-spec-2026-09) lists everything added later.
> For how the app works today, how to install it and how to change it, read
> [`PROJECT_GUIDE.md`](PROJECT_GUIDE.md). Dated changes: [`CHANGELOG.md`](CHANGELOG.md).

### Implementation status (last updated 2026-10-05)

| Area | Status |
|---|---|
| Phase 1 modules: Core, Registration, Reference Data, Admin Dashboard, Notification | **Built** |
| Registration form (4 steps, all 17 fields, validation, typo detection, email OTP, confirmation email + SMS) | **Built**, with changes: English UI and English-only data, classes 6–10, typed relation for "Other" (see 10.1) |
| Soft delete, audit log, edit history, unique WikiScholar ID | **Built** (ID year is configurable: `WS-2027-…`) |
| Region → district mapping (3.5), school entity resolution and merge tool (3.6) | **Built** |
| Admin roles, filters, multi-district groups, duplicate-school review | **Built** |
| Bulk email/SMS with batch IDs, delivery status, resend failed | **Built**, plus **named batches**, a "not delivered" filter, recipients CSV and a Students "Message history" filter (10.2). Email via Brevo SMTP/API or Gmail; SMS via MiM SMS. Email delivery reports via the Brevo webhook; SMS delivery reports not polled yet |
| Student batches (split a filtered list into groups of N) | **Built** (added later, 10.2) |
| Email & SMS credentials managed from the dashboard | **Built** (added later, 10.3) |
| Guardian declaration on the form; OTP/confirmation wording editable by a Super Admin | **Built** (added later, 10.1 / 10.3) |
| October 2026 form update: Bangla beside every English text, section, numbers-only roll, "how did you hear" survey, **date of birth removed**, HTML emails, grouped dashboard menu | **Built** (10.1 / 10.2) |
| City-corporation thanas, cantonments and "Other area" in the upazila list ("Upazila / Area") | **Built** (10.1): no area of Bangladesh is left out |
| Optional Cloudflare Turnstile; admins change their own password, Super Admin sets others' | **Built** (10.2, 2026-10-06) |
| Secure query interface for advanced users (5.2) | **Not built**: the filter panel covers the listed filters |
| Field-level encryption at rest (6) | **Not built**: TLS, disk encryption and least privilege are assumed; stored provider secrets are encrypted |
| Phase 2+ modules (Section 9) | **Not started**; the module registry and architecture are ready for them |

## 0. Context & Vision

This roadmap is therefore structured in two layers:

- **Phase 1 (build now):** Registration module only — but designed so none of the future vision is closed off.
- **Phase 2+ (future):** Exams, school/teacher CRM, volunteer tracking, call-center integration, and more.

The architecture and database design below keep both layers in mind from the start, so moving from Phase 1 to Phase 2 will not require rebuilding the system.

## 1. Core Principles

| **Principle** | **Meaning** |
|---|---|
| **Modular Monolith** | One codebase/deployment, but internally each feature is a fully self-contained module. A bug in one module cannot spread to another. |
| **Scalable by design** | Schema designed for thousands of users and for adding new tables/modules later. |
| **Never lose data** | No hard deletes. Always soft-delete + audit trail. |
| **Traceability** | Every action (who, when, what) is logged. |
| **Security-first** | Treated as a design requirement from day one, not an add-on. |
| **Policy-aligned** | Consistent with the Wikimedia Bangladesh Youth Safety Policy (details in Section 7). |
| **Data quality by design** | Free-text fields (like school name) are resolved to canonical records, not left as raw, inconsistent strings. |

## 2. System Architecture

### 2.1 Pattern: Modular Monolith

A single backend application, but each feature lives as an independent "module" — its own folder, its own database migrations, its own API routes — and modules talk to each other only through documented interfaces (no module reaches directly into another module's tables). If the system truly needs to scale to that level later, individual modules can be split into microservices — but going straight to microservices now would add unnecessary complexity.

### 2.2 Phase 1 Module List

1. **Core/Shared** — authentication, roles/permissions, unique ID generation, audit logging (used by every other module)
2. **Registration** — student registration form, validation, email verification
3. **Reference Data** — districts/upazilas/regions, canonical school list (lookup tables)
4. **Admin Dashboard** — filtering, sorting, data view, editing, school-merge tool
5. **Notification** — sending email and SMS, delivery reports

### 2.3 Future Modules (space reserved from the start)

1. Exam module
2. School–Teacher CRM module
3. Volunteer Visit Tracking module
4. Call-Center / Click-to-Call integration module
5. Analytics/Reporting module

### 2.4 Rules for Adding New Modules

- Every new module owns and migrates its own database tables; it never modifies another module's tables directly.
- New modules register themselves in a central "module registry" (routes, permissions, menu items).
- Feature modules depend on the Core module (users, auth, logging) — never the other way around; dependencies are always one-directional.
- Every module has its own tests, so adding/changing one module can be regression-tested without breaking others.

## 3. Database Design

### 3.1 Core Tables (Phase 1)

| **Table** | **Description** |
|---|---|
| `students` | name, date\_of\_birth, gender, district\_id, upazila\_id, school\_id, school\_name\_as\_entered, current\_class, class\_roll (nullable), student\_id\_sid (nullable), guardian\_name, guardian\_relation, phone, email, system-generated `wikischolar_id` |
| `schools` | canonical school name, district\_id, upazila\_id, `verification_status` (verified / pending) |
| `school_aliases` | alias\_text (as typed by a user), canonical `school_id` — lets future similar inputs auto-resolve |
| `regions` | region name (see Section 3.5) |
| `districts` | district name, `region_id` (foreign key), see 3.5 |
| `upazilas` | upazila name, `district_id` (foreign key) |
| `admins` | admin accounts — separate table, with roles/permissions/password hash |
| `audit_logs` | who did what, when, on which record (with before/after values) |
| `edit_history` | detailed version history of every edit (field, old value, new value, who made the change) |
| `email_batches` / `sms_batches` | which batch was sent to which students (by `wikischolar_id`) |
| `notification_logs` | delivery status of every email/SMS (sent/failed/bounced) |
| `email_verifications` | email verification OTP/token, expiry, status |

### 3.2 Relationships (simplified)

```
regions ──< districts ──< upazilas
districts ──< schools ──< students
school_aliases >── schools (many aliases per canonical school)
students ──< email_verifications
students ──< edit_history
students ──< email_batches/sms_batches (many-to-many via junction table)
admins ──< audit_logs (admin actions)
```

### 3.3 Soft-Delete Strategy

- No record is ever truly deleted.
- Every table has `is_deleted` (boolean), `deleted_at`, and `deleted_by` columns.
- "Deleting" a record removes it from the main list/view (so it disappears from the admin dashboard), but it stays intact in the database and can be restored from an "archived records" view when needed.
- Edits preserve the old value in `edit_history` — data is never lost, only new versions are added.

### 3.4 Unique ID

- Every student gets a system-generated `wikischolar_id`, e.g. `WS-2026-004821` (prefix + registration year + sequence).
- **Update:** the year part is the **programme year** from the setting `WS_ID_YEAR` (currently 2027, so IDs
  look like `WS-2027-000001`); leaving it empty uses the calendar year. Issued IDs never change.
- This is separate from the "Student ID (SID)" field on the form (the school's own ID, if it has one) — the two are kept in different columns so they are never confused.
- This ID is the primary key used to identify a person across future modules (exams, CRM, etc.).

### 3.5 Regional Division of Districts (Finalized Reference Data)

This is the **final, authoritative** Region → District mapping used for the district-selection auto-fill logic. All 64 districts of Bangladesh are covered across 6 operational regions used by this system. This table should be seeded directly into the `regions` and `districts` tables.

| **Region** | **Districts** |
|---|---|
| Dhaka | Dhaka, Faridpur, Gazipur, Gopalganj, Madaripur, Manikganj, Munshiganj, Narayanganj, Narsingdi, Rajbari, Shariatpur, Tangail, Mymensingh, Jamalpur, Sherpur, Netrokona |
| Khulna | Khulna, Bagerhat, Chuadanga, Jessore, Jhenaidah, Kushtia, Magura, Meherpur, Narail, Satkhira, Barisal, Patuakhali, Bhola, Pirojpur, Barguna, Jhalokati |
| Chittagong | Chittagong, Cox's Bazar, Rangamati, Bandarban, Khagrachari, Feni, Lakshmipur, Comilla, Noakhali, Chandpur |
| Sylhet | Sylhet, Moulvibazar, Habiganj, Sunamganj, Brahmanbaria, Kishoreganj |
| Rajshahi | Rajshahi, Bogra, Joypurhat, Naogaon, Natore, Chapainawabganj, Pabna, Sirajganj |
| Rangpur | Rangpur, Dinajpur, Gaibandha, Kurigram, Nilphamari, Lalmonirhat, Panchagarh, Thakurgaon |

Machine-readable form of the same mapping (for seed scripts / AI use):

```
{
  "Dhaka": ["Dhaka", "Faridpur", "Gazipur", "Gopalganj", "Madaripur", "Manikganj", "Munshiganj", "Narayanganj", "Narsingdi", "Rajbari", "Shariatpur", "Tangail", "Mymensingh", "Jamalpur", "Sherpur", "Netrokona"],
  "Khulna": ["Khulna", "Bagerhat", "Chuadanga", "Jessore", "Jhenaidah", "Kushtia", "Magura", "Meherpur", "Narail", "Satkhira", "Barisal", "Patuakhali", "Bhola", "Pirojpur", "Barguna", "Jhalokati"],
  "Chittagong": ["Chittagong", "Cox's Bazar", "Rangamati", "Bandarban", "Khagrachari", "Feni", "Lakshmipur", "Comilla", "Noakhali", "Chandpur"],
  "Sylhet": ["Sylhet", "Moulvibazar", "Habiganj", "Sunamganj", "Brahmanbaria", "Kishoreganj"],
  "Rajshahi": ["Rajshahi", "Bogra", "Joypurhat", "Naogaon", "Natore", "Chapainawabganj", "Pabna", "Sirajganj"],
  "Rangpur": ["Rangpur", "Dinajpur", "Gaibandha", "Kurigram", "Nilphamari", "Lalmonirhat", "Panchagarh", "Thakurgaon"]
}
```

### 3.6 Handling Free-Text School Names (Data Quality / Entity Resolution)

**Problem:** School name is a free-text field, so different users may type the same school differently (spelling variants, abbreviations, missing words). Left unmanaged, this creates duplicate, inconsistent school records and makes filtering/reporting by school unreliable.

**Solution (applied at both entry time and afterward):**

1. **Typeahead at entry:** as the user types, the form searches the canonical `schools` table using fuzzy matching (e.g. trigram similarity), scoped to the already-selected district/upazila, and suggests existing schools to pick from.
2. **New-school fallback:** if no match exists, the user can add a new school. This inserts a row into `schools` with `verification_status = pending` rather than silently treating it as a confirmed, permanent entry.
3. **Alias resolution:** the `school_aliases` table maps known alternate spellings to a canonical `school_id`. If typed text closely matches a stored alias, the system resolves it to the canonical school automatically.
4. **Dual storage:** every registration stores both `school_id` (the resolved, canonical reference used for all filtering/reporting) and `school_name_as_entered` (the raw text as typed, kept for audit — never overwritten or discarded).
5. **Admin merge tool:** the admin panel includes a "Duplicate School Review" view that surfaces schools with high name-similarity within the same district/upazila. An admin can merge duplicates into one canonical school; merging reassigns all linked students and is recorded in `audit_logs`. Merging never deletes the duplicate's history — it only redirects future references to the canonical record.

## 4. Registration Module — Feature Specification

### 4.1 Complete Form Structure & Flow

The form is presented in four steps:

**Step 1 — Student & Guardian Information** **Step 2 — Academic Information** **Step 3 — Contact & Email Verification** **Step 4 — Consent & Submit**

> **Update (built app):** the form is shown **in English**, not Bangla; the Bangla labels below are the
> original plan. All stored text must be English (Bangla digits are converted to 0–9). `current_class`
> is limited to **classes 6–10**. When `guardian_relation` is "Other", a typed relation
> (`guardian_relation_other`) is required. See Section 10.1.

| **#** | **Field (key)** | **Label shown to user (Bangla)** | **English meaning** | **Type** | **Required** | **Notes** |
|---|---|---|---|---|---|---|
| 1 | `student_name` | শিক্ষার্থীর পূর্ণ নাম | Student's Full Name | text | Yes | — |
| 2 | `date_of_birth` | জন্ম তারিখ | Date of Birth | date | Yes | — |
| 3 | `gender` | লিঙ্গ | Gender | select | Yes | Options: পুরুষ (Male) / নারী (Female) / উল্লেখ করতে আগ্রহী নই (Prefer not to say) |
| 4 | `guardian_name` | অভিভাবকের নাম | Guardian's Name | text | Yes | Mandatory for every registrant, regardless of age |
| 5 | `guardian_relation` | অভিভাবকের সাথে সম্পর্ক | Relation with Guardian | select | Yes | Options: বাবা (Father) / মা (Mother) / অন্যান্য (Other) |
| 6 | `district` | জেলা | District | select | Yes | Selecting this auto-fills Region (field 7) and loads the Upazila options (field 8) |
| 7 | `region` | অঞ্চল (স্বয়ংক্রিয়) | Region (auto-filled) | text (read-only) | — | Derived from `district`, not user-editable |
| 8 | `upazila` | উপজেলা | Upazila | select | Yes | Options load dynamically after `district` is chosen |
| 9 | `school_name` | বিদ্যালয়ের নাম | School Name | typeahead/autocomplete | Yes | See Section 3.6; includes "তালিকায় না থাকলে নতুন যোগ করুন" (Not in the list? Add new) |
| 10 | `current_class` | বর্তমান শ্রেণি | Current Class/Grade | select or text | Yes | — |
| 11 | `class_roll` | ক্লাস রোল | Class Roll | text/number | Conditional | See rule below |
| 12 | `student_id_sid` | স্টুডেন্ট আইডি (SID) | Student ID (school-issued) | text | Conditional | See rule below |
| 13 | `phone` | ফোন নম্বর | Phone Number | tel | Yes | Bangladeshi format |
| 14 | `email` | ইমেইল | Email | email | Yes | See typo-detection, Section 4.3 |
| 15 | `email_otp` | ইমেইল OTP | Email Verification Code | text | Yes | Required to unlock submission, Section 4.4 |
| 16 | `policy_consent` | আমি Wikimedia Bangladesh Youth Safety Policy পড়েছি এবং সম্মত আছি | I have read and agree to the Youth Safety Policy | checkbox | Yes | Registration cannot be completed unless checked |
| 17 | `updates_opt_in` | আমি ইমেইলের মাধ্যমে ভবিষ্যৎ WikiScholar আপডেট পেতে চাই | I want to receive future WikiScholar updates by email | checkbox | No | Optional |

**Rule for fields 11–12 (Class Roll / Student ID):** Both are individually optional, but **at least one of the two must be filled**; both may also be filled together. Both left empty is not allowed.

- Helper text shown under both fields: "ক্লাস রোল অথবা স্টুডেন্ট আইডি — অন্তত একটি অবশ্যই পূরণ করতে হবে।" (Fill in at least one of Class Roll or Student ID.)
- Error shown if both are empty on submit attempt: "ক্লাস রোল অথবা স্টুডেন্ট আইডির যেকোনো একটি পূরণ করুন।" (Please fill in either Class Roll or Student ID.)

**Static text always visible on the form:**

- Contact note: "কোনো প্রশ্ন থাকলে যোগাযোগ করুন: info@wikischolar.bd" (For any questions, contact: info@wikischolar.bd)
- Submit button (disabled until email is verified): "রেজিস্ট্রেশন সম্পন্ন করুন" (Complete Registration)
- Confirmation shown after successful submit: registration summary plus the assigned `wikischolar_id`, and a matching confirmation email is sent to the verified address.

### 4.2 Field-Level Validation Rules

| **Field** | **Rule** |
|---|---|
| `phone` | Must match a valid Bangladeshi mobile pattern (e.g. `01[3-9]XXXXXXXX`) |
| `email` | Standard email format check, plus typo detection (4.3) |
| `date_of_birth` | Must be a valid past date |
| `class_roll` / `student_id_sid` | See the either-or rule above |
| `policy_consent` | Must be checked before submission is allowed |
| `email_otp` | Must match the code sent for the entered email before submission is allowed |

### 4.3 Email Typo Detection

- Common domain misspellings (gamil.com, gnail.com, hotmial.com, yaho.com, etc.) are caught using a predefined list or a Levenshtein-distance algorithm.
- If a likely typo is detected, the user is not blocked — a **warning** is shown instead: "আপনি কি gmail.com লিখতে চেয়েছিলেন?" (Did you mean gmail.com?) — the user can correct it or confirm and proceed.
- **Update:** the hint is in English ("Did you mean name@gmail.com?"), appears **as the user types**
  (not only when the code is sent), offers a one-click fix, and also catches a missing or wrong dot
  (`gmailcom`, `gmail`, `gmail,com`).

### 4.4 Email Verification Flow

1. The user enters their email (field 14).
2. The system sends an OTP to that address.
3. The user enters the OTP (field 15). **Submission is blocked** until this succeeds.
4. Once verified, the rest of the form can be submitted.
5. On successful submission, a **confirmation email** is sent (registration summary, including the `wikischolar_id`).

### 4.5 Machine-Readable Form Schema

```
{
  "form_id": "wikischolar_registration",
  "steps": [
    {
      "step": 1,
      "title_bn": "শিক্ষার্থী ও অভিভাবকের তথ্য",
      "fields": [
        {"key": "student_name", "label_bn": "শিক্ষার্থীর পূর্ণ নাম", "type": "text", "required": true},
        {"key": "date_of_birth", "label_bn": "জন্ম তারিখ", "type": "date", "required": true},
        {"key": "gender", "label_bn": "লিঙ্গ", "type": "select", "required": true, "options_bn": ["পুরুষ", "নারী", "অন্যান্য"]},
        {"key": "guardian_name", "label_bn": "অভিভাবকের নাম", "type": "text", "required": true},
        {"key": "guardian_relation", "label_bn": "অভিভাবকের সাথে সম্পর্ক", "type": "select", "required": true, "options_bn": ["বাবা", "মা", "অন্যান্য"]}
      ]
    },
    {
      "step": 2,
      "title_bn": "শিক্ষাগত তথ্য",
      "fields": [
        {"key": "district", "label_bn": "জেলা", "type": "select", "required": true, "triggers": ["region_autofill", "upazila_load"]},
        {"key": "region", "label_bn": "অঞ্চল (স্বয়ংক্রিয়)", "type": "text", "required": false, "readonly": true, "derived_from": "district"},
        {"key": "upazila", "label_bn": "উপজেলা", "type": "select", "required": true, "depends_on": "district"},
        {"key": "school_name", "label_bn": "বিদ্যালয়ের নাম", "type": "typeahead", "required": true, "entity_resolution": true},
        {"key": "current_class", "label_bn": "বর্তমান শ্রেণি", "type": "select", "required": true},
        {"key": "class_roll", "label_bn": "ক্লাস রোল", "type": "text", "required": false},
        {"key": "student_id_sid", "label_bn": "স্টুডেন্ট আইডি (SID)", "type": "text", "required": false}
      ],
      "cross_field_rules": [
        {"rule": "at_least_one_required", "fields": ["class_roll", "student_id_sid"], "error_bn": "ক্লাস রোল অথবা স্টুডেন্ট আইডির যেকোনো একটি পূরণ করুন।"}
      ]
    },
    {
      "step": 3,
      "title_bn": "যোগাযোগ ও ইমেইল যাচাই",
      "fields": [
        {"key": "phone", "label_bn": "ফোন নম্বর", "type": "tel", "required": true, "pattern": "^01[3-9][0-9]{8}$"},
        {"key": "email", "label_bn": "ইমেইল", "type": "email", "required": true, "typo_check": true},
        {"key": "email_otp", "label_bn": "ইমেইল OTP", "type": "text", "required": true, "unlocks": "submit_button"}
      ]
    },
    {
      "step": 4,
      "title_bn": "সম্মতি ও জমা",
      "fields": [
        {"key": "policy_consent", "label_bn": "আমি Wikimedia Bangladesh Youth Safety Policy পড়েছি এবং সম্মত আছি", "type": "checkbox", "required": true},
        {"key": "updates_opt_in", "label_bn": "আমি ইমেইলের মাধ্যমে ভবিষ্যৎ WikiScholar আপডেট পেতে চাই", "type": "checkbox", "required": false}
      ]
    }
  ],
  "static_text": {
    "contact_note_bn": "কোনো প্রশ্ন থাকলে যোগাযোগ করুন: info@wikischolar.bd",
    "submit_button_bn": "রেজিস্ট্রেশন সম্পন্ন করুন",
    "submit_enabled_when": "email_otp verified AND policy_consent == true"
  }
}
```

## 5. Admin Panel — Feature Specification

### 5.1 Admin Management

- One admin can create another admin; admin data lives in a separate table (`admins`), fully isolated from student data.
- Role-based access (e.g., Super Admin, Admin, Read-only Viewer) so not everyone has every permission.

### 5.2 Dashboard & Filtering

- Filter/sort by any combination of district, region, upazila, school, class, gender, and registration date.
- Select multiple districts together to build a group (e.g., "everyone from these two districts").
- A secure **query interface** for advanced users — not direct access to the production database, but through a read-only replica/limited query builder (destructive queries blocked, with timeouts and rate limits). **Update: not built yet.**
- **Update (added):** the filtered list can be **split into batches** of a size the admin enters; each batch can be viewed, exported to CSV or messaged on its own (Section 10.2).
- **Duplicate School Review** tool (Section 3.6): surfaces likely duplicate schools for merging.

### 5.3 Bulk Email/SMS

- A filtered group can be selected and sent an email/SMS.
- Every send generates a **batch ID**, linked to each recipient's `wikischolar_id` — so later it's clear who received what, in which batch.
- **Update (added):** every batch also gets an admin-chosen **name**; batches can be searched by name, each batch's recipients filtered by status (incl. **not delivered**) and exported to CSV, and the student list filtered by "received / not sent yet / not delivered" for a batch.
- **Separate API integrations** for email and SMS (modular — if one goes down or fails, the other is unaffected).
- **Delivery reports:** sent/delivered/failed/bounced are tracked separately; failures appear in their own list, with a resend option.
- **Update:** providers are configured by a Super Admin on **Dashboard → Email & SMS settings** (Section 10.3).
  Email delivery reports arrive through a webhook; MiM SMS delivery reports (`/V2/DlrApi`) are wrapped in
  code but not polled yet, so SMS stay "sent".

### 5.4 Data Editing & Logging

- Admins can edit student data, but every edit is preserved in `edit_history` (who, when, what changed).
- Every admin action (login, edit, delete, sending messages, running queries, merging schools) is recorded in `audit_logs`.

## 6. Security

Since this system holds personal data of minors (name, date of birth, school, phone, guardian details, district/upazila), security is the most critical part of this project:

- **Encryption:** in transit (HTTPS/TLS) and at rest for sensitive fields in the database. **Update:** HTTPS is
  enforced; provider secrets (SMTP password, SMS API key) are stored encrypted; field-level encryption of
  student data is not built yet.
- **Access control:** role-based, following the principle of least privilege.
- **Rate-limiting & input sanitization:** to guard against form-level attacks (spam-bot registrations, SQL injection).
- **Backup & disaster recovery:** regular encrypted backups, with restore procedures actually tested.
- **Admin access auditing:** log not just edits but also who viewed/exported which data.
- **Third-party API minimization:** send email/SMS vendors only the data strictly needed to deliver the message.

## 7. Open Questions / Decisions Needed (before development starts)

- [ ] Should guardian phone/email also be mandatory (separate from guardian name/relation), to fully match the Youth Safety Policy? **Still open.**
- [x] Choosing email and SMS API vendors: **email** Brevo (SMTP relay or HTTPS API) or Google Mail/Workspace,
  chosen per installation on the dashboard; **SMS** MiM SMS.
- [ ] How much query access "advanced users" get, and who qualifies for it. **Still open** (query interface not built).
- [x] Finalizing the tech stack: **Django + PostgreSQL**, server-rendered pages (Section 8).

## 8. Suggested Tech Stack (for discussion, not final)

> **Update (decided and built):** Python 3.12 + **Django 5.1**, **PostgreSQL 13+** (16 recommended) with
> `pg_trgm`. The front end is **server-rendered Django templates with small vanilla JavaScript**, not React:
> simpler to host and audit, and the JSON endpoints can serve a React front end later. Email: Brevo / Google
> Mail; SMS: MiM SMS. Hosting: Docker on a VPS, or cPanel "Setup Python App" with an external PostgreSQL
> when the host's own PostgreSQL is too old (see `docs/DEPLOY_CPANEL.md`).

| **Layer** | **Suggestion** | **Reason** |
|---|---|---|
| Backend | Node.js (NestJS) or Python (Django) | Both support the modular-monolith structure well |
| Database | PostgreSQL | Relational, scalable, strong constraints/foreign keys, native trigram fuzzy search (`pg_trgm`) for school-name matching |
| Frontend | React | Well-suited for form-heavy UIs with dynamic dropdowns and typeahead fields |
| Email API | Amazon SES / Mailgun / Brevo | Reliable delivery reporting |
| SMS API | MiM SMS | More reliable delivery to Bangladeshi numbers |
| Hosting | Cloud VPS (encrypted volumes, regular backups) | Easier to secure and scale |

## 9. Future Roadmap (Phase 2+)

| **Phase** | **Module** | **Description** |
|---|---|---|
| Phase 2 | Exam module | Run exams on the same platform, linked to registration data via `wikischolar_id` |
| Phase 3 | School–Teacher CRM | Expand school profiles; add related teachers' names/designations/phone numbers |
| Phase 4 | Volunteer Visit Tracking | Log which volunteer visited which school, and when |
| Phase 5 | Call-Center Integration | Connect to an IP phone/softphone for one-click calling from the admin panel |
| Phase 6 | Analytics/Reporting | A chapter-growth tracking dashboard |

## 10. Built after the original spec (2026-09)

Features and decisions added while building and testing the MVP. Each is live and covered by tests.

### 10.1 Registration form
| Change | Why |
|---|---|
| Form, messages and emails in **English**; `LANGUAGE_CODE = en` | one language for users and data |
| **English-only data**: names, school, relation, roll and SID accept only A–Z, 0–9 and basic punctuation, in the browser and on the server; Bangla digits become 0–9 | avoid mixed scripts in the database; `find_non_english` lists older values |
| **Classes 6–10 only** (form + DB check constraint) | WikiScholar's target group |
| Guardian relation **"Other" requires a typed relation** (`guardian_relation_other`, DB check) | know who the guardian is |
| **Instant email typo hint** while typing, incl. missing/wrong dot | the old check only ran on "Send code" and missed `gmailcom` |
| Header shows the **WikiScholar logo** and a **"Back to wikischolar.bd"** link (`WS_SITE_URL`), also on the success screen | the form is reached from the main site |
| Email step says the code is sent **by email only** and to **check Spam/Junk** | codes were missed in spam folders |
| **One email per student**: "Send verification code" warns that the address is already registered and asks for another; re-checked on submit | avoid duplicate student records sharing one inbox |
| **Confirmation SMS** after registering (besides the email): "registration successful", the WikiScholar ID and the contact address, within one 160-character SMS; verification stays email-only | the student gets the ID on their phone too |
| School typeahead suggests **approved (verified) schools only**; pending ones are still matched on submit | students should pick from the approved list; staff approve new schools |
| **Required guardian declaration** at the start ("I am the guardian of the student named below and I am filling in this form on their behalf"), stored with a timestamp, shown in the summary, confirmation, dashboard (filter + export) | Youth Safety Policy: the guardian fills in the form |
| **Answers never lost**: draft kept in the browser tab, browser Back/Forward move between steps, finished steps clickable | users lost data with the browser's Back button |
| WikiScholar ID year = **programme year** (`WS_ID_YEAR`, now 2027) | IDs start `WS-2027-` |
| **Upazila / Area**: the thanas of all 13 city corporations, the 31 cantonments and an "Other area (not listed)" per district join the 503 upazilas, grouped in the dropdown | city corporations have no upazila; nobody should be unable to choose their area |
| **Bangla beside every English text** on the form (labels, hints, buttons, options, messages), smaller and in natural Bangla; answers stay English | guardians read Bangla more easily; the data stays one script |
| **Date of birth removed** from the form, database (column dropped), emails, dashboard and export | no longer needed (supersedes field 2 in 4.1 and its rule in 4.2) |
| **Section** (optional, with instructions) and **class roll numbers only** | classes with sections; rolls are numbers |
| School suggestions from the **whole district** (own area first, area shown); a picked school may be in another area | students attend schools outside their own upazila / thana; schools filed under a neighbouring area were missed |
| **"How did you hear about WikiScholar?"** dropdown (7 options) in step 4, counted on the dashboard Overview | know which outreach works |
| English logo in the header; site icon; Youth Safety Policy link now `https://wikischolar.bd/youth-policy` | new branding and policy page |
| **HTML emails** (logo, card, OTP code box, details table) with the plain text kept as the second part | emails get noticed and are easier to read |
| Success screen: **Print / Save as PDF** (browser print with a print stylesheet; no PDF library), "Registered on" date, cleaner card without a coloured strip | families keep a copy of the WikiScholar ID |

### 10.2 Admin dashboard
| Change | Why |
|---|---|
| **Student batches**: split the filtered list into batches of N (oldest first by default, so batches stay stable), each viewable / exportable / messageable; message batches record which student batch they went to | run activities in fixed-size groups |
| Warning banners when email or SMS is **not really being delivered** (console backend) | a registration "sent" email that reached nobody |
| **Named message batches**; Messages list search / channel / "undelivered" filter with per-status counts | track what was sent to whom |
| Batch page: filter recipients by status incl. **Not delivered**, search, **CSV export**, resend not delivered, "Show these students" | follow up on failures |
| Students → **Message history** filter (received / not sent yet / not delivered) | send only to the students a batch missed |
| Reliable bulk sending: chunked from the browser with automatic continuation, rows claimed once (`SKIP LOCKED`), braces in text no longer crash, works on pooled DB connections, clear provider errors, explanation when 0 recipients (opt-in) | bulk email failed on the first cPanel install while OTP worked |
| Admin edits follow the same English-only and class rules; school and location names are English-only | consistent data |
| Sidebar tools in **collapsible groups** (Students, Schools & places, Messaging, Administration) with the logo on top | the menu had grown to 11 links |
| **Change password** for every admin; Super Admin **sets a new password** for others | admins could not change a temporary password, and a forgotten one needed a server command |
| Optional **Cloudflare Turnstile** on "Send verification code" and sign-in | stop bots sending emails through the form and guessing passwords |
| **Schools without an area**: the CSV import accepts a blank upazila / area (or no such column); those schools belong to the whole district (suggested, matched and duplicate-checked across its areas) until an admin sets the area; *Area not known* filter | the school lists available have districts but not always upazilas |

### 10.3 Email & SMS settings (Super Admin)
| Change | Why |
|---|---|
| **Email providers** from the dashboard: Brevo SMTP relay, **Brevo HTTPS API** (port 443, for hosts that block SMTP), Google Mail/Workspace (App password), any SMTP, console | vendor chosen per installation; shared hosts often block SMTP |
| **Reply-to** on every email (OTP, confirmation, bulk, test), default `info@wikischolar.bd` (`WS_REPLY_TO`), editable in Email settings | replies go to the programme's inbox |
| **Brevo delivery webhook** (`/notifications/webhook/email/?token=…`): delivered / bounced per message | know which emails really arrived |
| **System emails** page: a Super Admin edits the OTP and confirmation email subject/text with placeholders, preview, test send, reset to default | wording changes without a code release |
| **MiM SMS** credentials (API username, API key, Sender ID), test SMS, balance check | SMS vendor decided |
| Secrets stored **encrypted** (`WS_CREDENTIALS_KEY`), never shown again, never in the audit log | minors' data platform, least exposure |
| Test email / test SMS before activating | avoid silently broken delivery |

### 10.4 Operations and deployment
| Change | Why |
|---|---|
| **cPanel support**: `passenger_wsgi.py`, `.env` file loading, database cache (`DJANGO_CACHE=db`) instead of Redis, `docs/DEPLOY_CPANEL.md`, `docs/cpanel.env.example` | the organisation's hosting is cPanel |
| **External PostgreSQL** (e.g. Neon) documented for hosts whose PostgreSQL is too old (Django 5.1 needs 13+) | the cPanel host had PostgreSQL 9.6 |
| `manage.py check_host` pre-flight (Python, PostgreSQL version, `pg_trgm`, settings, migrations, cache) | catch setup problems before they become error 500 |
| 500 errors logged with tracebacks (`stderr.log` on cPanel) | errors were invisible with debug off |
| `scripts/build_cpanel_zip.py` builds the upload package without local or secret files | repeatable deployments |

### 10.5 Next steps (suggested)
1. Poll MiM SMS delivery reports (`/V2/DlrApi`) about 5 minutes after sending; consider `/V2/OneToMany` for very large sends.
   (Email delivery reports already arrive through the Brevo webhook.)
2. Duplicate-student detection (same name + date of birth + school) with a review/merge screen.
3. Two-factor authentication for admins (at least Super Admins).
4. Decide the guardian phone/consent question (Section 7), then add the fields.
5. Saved queries / limited query builder (Section 5.2).
6. Field-level encryption of phone, email and guardian name.
7. A real job queue (Celery/RQ) if bulk volumes outgrow the cron-driven `send_queued`.
8. Phase 2: the Exam module, as a new app using `wikischolar_id` (Section 9).
