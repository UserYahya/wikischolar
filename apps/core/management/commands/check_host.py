"""Pre-flight for a new server (cPanel or any other): can this host run WikiScholar?"""
import sys

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = "Check the database, Python and production settings of this server before `migrate`."

    def handle(self, *args, **opts):
        self.problems = 0
        self.item(sys.version_info >= (3, 10), f"Python {sys.version.split()[0]}", "Django 5.1 needs Python 3.10 or newer.")

        try:
            with connection.cursor() as cur:
                cur.execute("SHOW server_version_num")
                version = int(cur.fetchone()[0])
                cur.execute("SELECT rolsuper FROM pg_roles WHERE rolname = current_user")
                superuser = bool(cur.fetchone()[0])
                cur.execute("SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm'")
                installed = cur.fetchone() is not None
                cur.execute("SELECT 1 FROM pg_available_extensions WHERE name = 'pg_trgm'")
                available = cur.fetchone() is not None
                cur.execute("SELECT has_database_privilege(current_database(), 'CREATE')")
                can_create = bool(cur.fetchone()[0])
        except Exception as exc:  # wrong credentials, no PostgreSQL, etc.
            advice = str(exc).strip()
            if "or later is required" in advice:
                advice += (" The host's PostgreSQL is too old: use an external PostgreSQL 16 service "
                           "(see docs/DEPLOY_CPANEL.md, 'If the host's PostgreSQL is too old').")
            self.item(False, "PostgreSQL connection", advice)
            return self.finish()

        self.item(version >= 130000, f"PostgreSQL {version // 10000}.{version % 10000}",
                  "PostgreSQL 13 or newer is required by Django 5.1 (16 recommended).")
        if installed:
            self.item(True, "pg_trgm extension", "")
        else:
            # Since PostgreSQL 13, pg_trgm is a "trusted" extension: a database owner may create it.
            creatable = available and (superuser or (version >= 130000 and can_create))
            self.item(creatable, "pg_trgm extension can be created by migrate",
                       "Ask your host to run  CREATE EXTENSION pg_trgm;  in this database "
                       "(or to give PostgreSQL 13+). Without it, school search cannot work.")

        if settings.DATABASES["default"].get("DISABLE_SERVER_SIDE_CURSORS"):
            self.item(True, "Pooled database connection: server-side cursors are off (required for PgBouncer)", "")
        self.item(not settings.DEBUG, "DJANGO_DEBUG is off", "Set DJANGO_DEBUG=0 in .env for a public site.")
        self.item(settings.SECRET_KEY and "change-me" not in settings.SECRET_KEY, "DJANGO_SECRET_KEY is set",
                   "Put a long random DJANGO_SECRET_KEY in .env.")
        hosts = [h for h in settings.ALLOWED_HOSTS if h not in ("localhost", "127.0.0.1", "[::1]")]
        self.item(bool(hosts), f"ALLOWED_HOSTS = {', '.join(settings.ALLOWED_HOSTS) or '(empty)'}",
                  "Set DJANGO_ALLOWED_HOSTS (and DJANGO_CSRF_TRUSTED_ORIGINS) to your real domain.")
        self.database_state()
        self.cache_works()
        backend = settings.CACHES["default"]["BACKEND"].rsplit(".", 2)[-2]
        self.item(backend != "locmem", f"Shared cache ({backend})",
                   "Set DJANGO_CACHE=db and run `manage.py createcachetable`, so rate limits are shared "
                   "between app processes.", warn_only=True)
        return self.finish()

    def database_state(self):
        """After `migrate`: nothing left unapplied, and the cache table exists when DJANGO_CACHE=db."""
        from django.db.migrations.executor import MigrationExecutor
        executor = MigrationExecutor(connection)
        pending = executor.migration_plan(executor.loader.graph.leaf_nodes())
        self.item(not pending, "All migrations applied" if not pending else f"{len(pending)} migration(s) not applied",
                  "Run `python manage.py migrate` (normal before the first migrate).", warn_only=True)
        cache = settings.CACHES["default"]
        if cache["BACKEND"].endswith("DatabaseCache"):
            exists = cache["LOCATION"] in connection.introspection.table_names()
            self.item(exists, f"Cache table {cache['LOCATION']}",
                      "Run `python manage.py createcachetable` (sign-in and OTP fail with error 500 without it).")

    def cache_works(self):
        """Sign-in, OTP and the lookup API all use the cache: an unreachable one means error 500."""
        from django.core.cache import cache
        try:
            cache.set("check_host", "ok", 10)
            ok, error = cache.get("check_host") == "ok", ""
        except Exception as exc:
            ok, error = False, str(exc).strip().rstrip(".")
        advice = error
        if settings.CACHES["default"]["BACKEND"].endswith("RedisCache"):
            advice += (". REDIS_URL is set but Redis isn't reachable: remove REDIS_URL from .env and from "
                       "Setup Python App's environment variables, set DJANGO_CACHE=db, run createcachetable.")
        self.item(ok, "Cache works", advice)

    def item(self, ok, label, advice, warn_only=False):
        if ok:
            self.stdout.write(self.style.SUCCESS(f"  OK    {label}"))
        elif warn_only:
            self.stdout.write(self.style.WARNING(f"  WARN  {label}: {advice}"))
        else:
            self.problems += 1
            self.stdout.write(self.style.ERROR(f"  FAIL  {label}: {advice}"))

    def finish(self):
        if self.problems:
            self.stdout.write(self.style.ERROR(f"{self.problems} problem(s): fix them before `migrate`."))
            sys.exit(1)
        self.stdout.write(self.style.SUCCESS("This host can run WikiScholar."))
