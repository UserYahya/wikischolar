# Database

PostgreSQL 13+ (16 recommended) with the `pg_trgm` extension. The complete DDL (tables, constraints, indexes,
trigger functions) is in [`schema.sql`](schema.sql), generated with
`pg_dump --schema-only` from the migrated database. Migrations remain the source of truth.

## Entity-relationship diagram

```mermaid
erDiagram
    regions ||--o{ districts : "groups (nullable, editable)"
    districts ||--o{ thanas : contains
    thanas ||--o{ schools : contains
    districts ||--o{ schools : "denormalised"
    schools ||--o{ school_aliases : "alternate spellings"
    schools |o--o{ schools : "merged_into"
    districts ||--o{ students : "lives in"
    thanas ||--o{ students : "lives in"
    schools ||--o{ students : attends
    students ||--o{ edit_history : "field changes"
    students |o--o{ email_verifications : "verified by"
    students ||--o{ notification_logs : receives
    email_batches ||--o{ notification_logs : "recipients"
    sms_batches ||--o{ notification_logs : "recipients"
    notification_logs |o--o{ notification_logs : "resend_of"
    admins ||--o{ audit_logs : "acts"
    admins ||--o{ edit_history : "changed_by"
    admins ||--o{ email_batches : "created_by"
    admins ||--o{ sms_batches : "created_by"
    admins |o--o{ email_settings : "updated_by"
    admins |o--o{ sms_settings : "updated_by"

    regions {
      bigint id PK
      slug code UK
      text name
      text name_bn
      smallint sort_order
      bool is_deleted
    }
    districts {
      bigint id PK
      slug code UK
      text name
      text name_bn
      bigint region_id FK "NULL = unassigned"
      bool is_deleted
    }
    thanas {
      bigint id PK
      bigint district_id FK
      text name "unique per district"
      text name_bn
      text group "blank = thana; Cantonment or Other"
      text group_bn
    }
    schools {
      bigint id PK
      text name
      text name_normalized "GIN trigram"
      bigint district_id FK
      bigint thana_id FK "blank = thana not known (whole district)"
      text verification_status "verified|pending|merged"
      text source
      bigint merged_into_id FK
      text eiin "6 digits, unique when set"
      text management "government data (BANBEIS)"
      text education_level
      text area_status
    }
    school_aliases {
      bigint id PK
      bigint school_id FK
      text alias_text
      text alias_normalized "GIN trigram"
      text source
    }
    students {
      bigint id PK
      text wikischolar_id UK "WS-2027-000001"
      text filled_by "student|guardian"
      timestamptz guardian_declared_at "set when a guardian declared"
      text student_name
      text gender
      text guardian_name
      text guardian_relation "father|mother|other"
      text guardian_relation_other "filled only when other"
      bigint district_id FK
      bigint thana_id FK "must belong to district"
      bigint school_id FK
      text school_name_as_entered "exactly as typed"
      text school_resolution
      text current_class "CHECK 6..10"
      text class_roll "digits (form check)"
      text student_id_sid
      text section "optional"
      text phone "CHECK BD mobile format"
      text email
      timestamptz email_verified_at
      timestamptz policy_consent_at
      text policy_version
      bool updates_opt_in
      text heard_from "survey; CHECK choice or empty"
      bool is_deleted
    }
    email_verifications {
      uuid id PK
      text email
      text code_hash "HMAC, never the code"
      text status
      smallint attempts
      timestamptz expires_at
      bigint student_id FK
    }
    edit_history {
      bigint id PK
      bigint student_id FK
      uuid change_set
      text field_name
      jsonb old_value
      jsonb new_value
      text reason
      bigint changed_by_id FK
    }
    email_batches {
      bigint id PK
      text batch_code UK "EB-2026-0001"
      text name "admin label, searchable"
      text subject
      text body
      jsonb filter_snapshot
      bool opted_in_only
      int recipient_count
      text status
    }
    sms_batches {
      bigint id PK
      text batch_code UK "SB-2026-0001"
      text name "admin label, searchable"
      text body
      jsonb filter_snapshot
      int recipient_count
      text status
    }
    notification_logs {
      bigint id PK
      text channel "email|sms"
      text kind "otp|confirmation|bulk"
      bigint email_batch_id FK
      bigint sms_batch_id FK
      bigint student_id FK
      text wikischolar_id
      text destination
      text status "queued|sent|delivered|failed|bounced"
      text provider_message_id
      bigint resend_of_id FK
    }
    admins {
      bigint id PK
      text email UK
      text full_name
      text role "super_admin|admin|viewer"
      bool is_active
      bool is_deleted
    }
    email_templates {
      bigint id PK
      text key UK "registration.otp, registration.confirmation"
      text subject
      text body "with {placeholders}"
      bool is_customized "false = code default in use"
    }
    email_settings {
      bigint id PK "always 1"
      text provider "brevo|brevo_api|gmail|smtp|console"
      text host
      int port
      text security "starttls|ssl|none"
      text username
      text password_encrypted "Fernet, WS_CREDENTIALS_KEY"
      text from_email
      text from_name
      text reply_to "optional"
      bool is_active
    }
    sms_settings {
      bigint id PK "always 1"
      text provider "mimsms|console"
      text api_url
      text username "MiM SMS login email"
      text api_key_encrypted "Fernet"
      text sender_name
      bool is_active
    }
    audit_logs {
      bigint id PK
      bigint actor_id FK
      text actor_type
      text action
      text entity_type
      text entity_id
      jsonb before
      jsonb after
      jsonb meta
      inet ip_address
      timestamptz created_at
    }
```

`id_sequences (scope, year, last_value)` backs WikiScholar IDs and batch codes (the student ID
year is `WS_ID_YEAR`, default 2027). Django's own tables (`django_session`,
`django_content_type`, `auth_permission`, …) are omitted, as is `ws_cache`, the database cache
table created by `manage.py createcachetable` when `DJANGO_CACHE=db` (rate limits on hosts without
Redis; its rows are disposable).

## Tables by module

| Module | Table | Notes |
|---|---|---|
| Core | `admins` | Dashboard accounts. Deactivation = soft delete + `is_active=false`. |
| | `audit_logs` | Every sensitive action, including record views and exports. Append-only. |
| | `id_sequences` | Per-scope, per-year counters, allocated atomically with `ON CONFLICT DO UPDATE … RETURNING`. |
| Reference | `regions` | Editable in the dashboard. |
| | `districts` | `region_id` nullable and editable — the mapping is data. |
| | `thanas` | The government's thana list (BANBEIS e-survey 2024) plus newer upazilas, cantonments and one "Other thana" per district. Unique `(district_id, name)`; also unique `(id, district_id)` to support the composite FK. Called `upazilas` until migration `reference.0006` (Oct 2026). |
| | `schools` | Canonical list + pending registrant entries; merged rows are kept and point to `merged_into_id`. Names are stored in capitals. Government data from the BANBEIS list (`import_banbeis_schools`): `eiin` (unique when set, 6 digits — `school_eiin_uniq`, `school_eiin_six_digits`), `division`, `institute_type`, `education_level`, `management`, `mpo`, `institute_for`, `geographical_position`, `area_status`, `post_office`, `email`; blank when unknown. |
| | `school_aliases` | Alternate spellings; unique per school on the normalised text. |
| Registration | `students` | Region is not stored — derived via `district.region_id`. No date of birth (column dropped in migration `registration.0006`, October 2026). `section` is optional; `heard_from` is the "How did you hear about WikiScholar?" answer (empty for older rows). |
| | `email_verifications` | OTP attempts; UUID PK so IDs are unguessable. |
| | `edit_history` | One row per changed field; rows from one save share `change_set`. Append-only. |
| Dashboard | `saved_searches` | Advanced searches saved by admins and shared with everyone who can see that list: `entity` (students / schools), `name` (unique per entity among live rows), `description`, `query` (JSON, re-checked whenever it runs), `created_by`, `updated_by`. Archived, never deleted. |
| Notification | `email_batches`, `sms_batches` | One per bulk send, with an admin-chosen `name` (indexed, for search and the Students "Message history" filter); the filter used is stored as JSON. |
| | `notification_logs` | One row per recipient per attempt (also OTP and confirmation emails, and the confirmation SMS). `status` queued → sent → delivered, or failed / bounced ("not delivered"); `provider_message_id` is what delivery webhooks match (our Message-ID for SMTP, Brevo's `messageId` for the Brevo API). Queued rows are claimed with `SELECT … FOR UPDATE SKIP LOCKED`, so parallel senders never send one twice. |
| | `email_templates` | Super Admin wording of system emails, one row per registered key. "Reset to default" sets `is_customized=false` (no delete); changes are audited with before/after text. |
| | `email_settings`, `sms_settings` | One row each (pk 1): provider credentials entered by a Super Admin. Secrets are Fernet-encrypted and never audited; `is_active` decides whether they override the env settings. |

## Integrity enforced by the database

These hold even if application code has a bug or someone uses `psql` directly.

**No hard deletes.** A `BEFORE DELETE` trigger calling `ws_forbid_delete()` rejects deletes on
`students`, `schools`, `school_aliases`, `regions`, `districts`, `thanas`, `admins`, `saved_searches`,
`email_verifications`, `email_batches`, `sms_batches` and `notification_logs`. Records are
archived with `is_deleted / deleted_at / deleted_by`. In Django, `.delete()` on these models
raises; `soft_delete()` and `restore()` are used instead, and the default manager hides
archived rows (`all_objects` shows them).

**Append-only history.** `ws_append_only()` rejects `UPDATE` and `DELETE` on `audit_logs` and
`edit_history`.

**Checks and keys.**
* `student_phone_bd_format` — `phone ~ '^01[3-9][0-9]{8}$'` (stored normalised, 11 digits).
* `student_roll_or_sid` / `student_roll_or_sid_not_blank` — class roll or SID must be non-blank.
* `student_class_6_to_10` — `current_class IN ('6'..'10')`.
* `student_heard_from_valid` — the survey answer `heard_from` is one of its choices, or empty for
  students who registered before the question existed.
* `student_guardian_declaration` — `filled_by = 'guardian'` exactly when `guardian_declared_at` is set.
* `student_relation_other_text` — `guardian_relation_other` is non-blank exactly when
  `guardian_relation = 'other'`.
  Both were added `NOT VALID`: enforced for every new or updated row, while rows registered before
  the rule are kept unchanged (fix them from the dashboard; `manage.py find_non_english` lists
  non-English text).
* `students_thana_in_district` — composite FK `(thana_id, district_id) → thanas(id, district_id)`,
  so a student's thana must belong to their district. Declared `DEFERRABLE INITIALLY
  DEFERRED`; checked at commit.
* `school_merged_has_target` — `merged` status ⇔ `merged_into_id` set.
* `notif_single_batch`, `notif_batch_matches_channel` — a log belongs to at most one batch, of
  its own channel.
* `thana_district_name_uniq` — a thana name is unique within its district; cantonments and "Other
  thana" are `thanas` rows too (told apart by `group`), so they share this rule and the composite key
  above.
* Unique: `students.wikischolar_id`, `admins.email`, `regions.code`, `districts.code`,
  batch codes, `(scope, year)` in `id_sequences`.
* Foreign keys to students, schools and places use `ON DELETE PROTECT` semantics.

## Indexes that matter

* `school_name_trgm`, `alias_text_trgm` — GIN `gin_trgm_ops` for typeahead and duplicate
  detection.
* `school_thana_status_idx (thana_id, verification_status)` — typeahead scope.
* `student_location_idx (district_id, thana_id)`, `student_school_idx`, `student_gender_idx`,
  plus single-column indexes on `current_class`, `created_at`, `email`, `phone`,
  `is_deleted` — the dashboard filters.
* `audit_entity_idx (entity_type, entity_id)`, `audit_logs.created_at`, `action`.
* `notification_logs (status)`, `(provider_message_id)` — delivery reports and webhooks.

## Reference data

`data/reference_seed.json`: 6 regions, 64 districts (each with a region **code** only as its
initial assignment) and 666 thanas, all with Bangla names: the districts and the 560 thanas of the
government's BANBEIS institution list (e-survey 2024; names cleaned, three district typos fixed), the
11 upazilas created after that survey, 31 cantonments and one "Other thana (not listed)" per
district. `scripts/build_thana_seed.py` builds it from the sheet; `data/thana_mapping.csv` records,
for each thana, the old "Upazila / Area" row it replaced (Bangla names were carried over from there)
and, for each retired old row, where its students and schools went. Migration `reference.0007`
applies that mapping to an existing database. Add or rename thanas later from **Dashboard →
Locations → district**.

## Backups & retention (recommended)

Daily `pg_dump` (or managed PITR), kept encrypted off-site, with a quarterly restore test.
Decide a retention period for `email_verifications` and OTP `notification_logs` (they can be
archived after, say, 90 days) as part of the data-protection policy.
