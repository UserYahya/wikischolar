# Development chat summary

A short record of the AI-assisted (Claude Code) sessions that built WikiScholar: what was asked, what was
decided and what went wrong. Use it with [`PROJECT_GUIDE.md`](../PROJECT_GUIDE.md) and
[`CHANGELOG.md`](../CHANGELOG.md) (the changelog has the detail of every change).

It contains **no secrets**. Passwords, API keys, database URLs and `.env` contents from the chats are left out on
purpose. A database password was once pasted into a chat; the advice was to reset it. Never paste secrets into chats.

## 1. Phase 1: building the platform

The first chat built the platform from
[`WikiScholar Registration & Database Platform — Complete Roadmap.md`](../WikiScholar%20Registration%20%26%20Database%20Platform%20%E2%80%94%20Complete%20Roadmap.md):

- A Django 5.1 + PostgreSQL **modular monolith** with the modules core, reference, registration,
  notifications and dashboard.
- The registration form with email OTP, and reference data (regions, districts, upazilas, schools with
  trigram matching).
- The admin dashboard, bulk email/SMS, and a Docker setup.

**Standing rule:** keep the modular-monolith structure. New modules must not break existing ones. Modules
call each other through `services.py`, register navigation with `apps.core.registry.register_nav`, and use the
permission codes in `apps/core/permissions.py`.

## 2. Running it locally (Windows)

- Portable PostgreSQL 16 in `.pgsql` / `.pgdata`, a `.venv`, and `run-dev.ps1` to start everything.
- **Lesson:** the `pgserver` package lacked `pg_trgm`, so the project switched to the EDB portable binaries.

## 3. Feature requests, in order

| # | Request | Result |
|---|---|---|
| 1 | Classes 6–10 only | form + DB constraint (added `NOT VALID`, so older rows are kept) |
| 2 | Relation "Other" | a text box that must be filled in |
| 3 | Email credentials in the dashboard (Super Admin) | Email settings: Brevo, Gmail, other SMTP; secrets encrypted |
| 4 | Split students into batches | batches of N on the Students page |
| 5 | Form in English, English-only data | all texts English; stored free text validated |
| 6 | Email typo hint not working | instant hint, including missing or wrong dots |
| 7 | Back button loses data | draft + history: Back and reload keep answers |
| 8 | Student ID format | `WS-2027-000001` |
| 9 | SMS credentials | MiM SMS provider, test SMS, balance |
| 10 | Host on cPanel | `passenger_wsgi.py`, `.env` loading, DB cache, `check_host`, `docs/DEPLOY_CPANEL.md`, zip builder |
| 11 | A document another person (or an AI) can understand | `PROJECT_GUIDE.md` |
| 12 | Keep docs current | roadmap status + `CHANGELOG.md`; **every change updates the docs** |
| 13 | Header logo, "Back to wikischolar.bd", OTP spam note, approved schools only, reply-to `info@wikischolar.bd`, bulk email fixes, named batches, "not delivered" filter | all done (CHANGELOG "second update") |
| 14 | Guardian declaration; editable system emails | declaration (later **mandatory**); Dashboard → System emails |
| 15 | Header looked bad; subject box too large | new slim header; hashed static file names; grid fix |
| 16 | Private GitHub repository without private info | https://github.com/UserYahya/wikischolar (private) |
| 17 | Warn when an email is already registered | "Send verification code" refuses a used address (409); re-checked on submit; archived students free it |
| 18 | City corporations have no upazila: how to fit them in (plan only, then built in #21) | agreed: extra rows in `upazilas` with a `group` (thanas per city corporation, cantonments, "Other area" per district), label "Upazila / Area", minimal structural change |
| 19 | October 2026 list of ten: logos and favicon, HTML emails, grouped dashboard menu, Bangla beside every form text, "guardian" wording, remove date of birth, numbers-only roll, optional section, "how did you hear" survey, new Youth Policy link | all done (CHANGELOG 2026-10-05); date-of-birth column dropped |
| 20 | Keep only the English logo in the header; review the form's design/UX | Bangla logo kept in `docs/brand/`; review fixed a wrong Bangla label, a focus box, step 2 order, small Bangla text, cut-off placeholders, the success screen |
| 21 | Build the upazila/thana plan | 105 thanas of 13 city corporations, 31 cantonments, "Other area"; research found 503 upazilas (8 created in Jun–Jul 2026) and Bogura City Corporation (May 2026) |
| 22 | Cloudflare Turnstile; admin password change; Section "(if any)"; "Banner / leaflet etc." | Turnstile optional (on with two `.env` keys); Change password page + Super Admin "Set new password" |

## 4. cPanel deployment problems met (and fixes)

| Symptom | Cause | Fix |
|---|---|---|
| `activate: No such file or directory` | wrong virtualenv path | copy the exact command from Setup Python App |
| `failed to resolve host 'db'` | `.env` made from the Docker `.env.example` | use `docs/cpanel.env.example` |
| PostgreSQL 9.6 found | host's PostgreSQL too old | external PostgreSQL (Neon) |
| `relation "admins" does not exist` | `migrate` not run | run `migrate` before `create_super_admin` |
| 500 on sign-in, `redis:6379` in log | leftover `REDIS_URL` | remove it, `DJANGO_CACHE=db`, `createcachetable` |
| SMTP blocked / timeouts | host blocks port 587/465 | **Brevo HTTPS API** provider (port 443) |
| Bulk email failed, OTP worked | server-side cursors on a pooled Neon connection, among other causes | cursors off for pooled hosts, chunked sending, visible errors |
| Huge logo after an update | browser cached the old CSS | content-hashed static names; run `collectstatic` after every upload |

Other lessons:

- A local preview once tried real SMTP. It failed with `535`, so nothing was sent. Local previews must use the
  console backend.
- Facts that change (upazila counts, city corporations, police thanas) were researched on the web and
  spot-checked against news reports; the coverage test in `tests/test_areas.py` pins the counts, so update
  it together with the seed when new units are created.
- Manifest static storage raised errors for a missing file. `ForgivingManifestStorage` falls back to the plain
  name instead.

## 5. How to update the live site

Build `python scripts/build_cpanel_zip.py`, then upload and extract the zip into the app root. Then, after the
virtualenv command, run:

- `migrate`
- `collectstatic --noinput`
- `check_host`

Finally, Restart in Setup Python App. The full steps are in `docs/DEPLOY_CPANEL.md` §8b.

## 6. Working with an AI on this project

- Read `PROJECT_GUIDE.md` first; it explains the architecture, rules and prompting tips.
- Keep the modular monolith. After each change, run the tests, then update the affected docs and `CHANGELOG.md`.
- Never commit `.env`, keys or database dumps; `.gitignore` already excludes them.
