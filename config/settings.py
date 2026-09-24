"""
WikiScholar settings. Everything environment-specific comes from env vars
(see .env.example). No secrets or reference data live in code.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv(path):
    """Read KEY=value lines from .env (for hosts like cPanel without a process manager).
    Real environment variables always win; nothing is overwritten."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key.strip(), value)


_load_dotenv(BASE_DIR / ".env")


def env(key, default=None):
    return os.environ.get(key, default)


def env_bool(key, default=False):
    return str(env(key, str(default))).lower() in ("1", "true", "yes", "on")


DEBUG = env_bool("DJANGO_DEBUG", False)
SECRET_KEY = env("DJANGO_SECRET_KEY") or ("dev-insecure-key-change-me" if DEBUG else None)
if not SECRET_KEY:
    raise RuntimeError("DJANGO_SECRET_KEY must be set when DJANGO_DEBUG is off.")

ALLOWED_HOSTS = [h.strip() for h in env("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h.strip()]
CSRF_TRUSTED_ORIGINS = [o.strip() for o in env("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if o.strip()]

# ---- Modules (modular monolith). Core first: every feature module depends on it.
INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    "apps.core",
    "apps.reference",
    "apps.notifications",
    "apps.registration",
    "apps.dashboard",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.dashboard.middleware.DashboardLanguageMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "templates"],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
        "apps.core.context_processors.platform",
    ]},
}]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("DB_NAME", "wikischolar"),
        "USER": env("DB_USER", "wikischolar"),
        "PASSWORD": env("DB_PASSWORD", "wikischolar"),
        "HOST": env("DB_HOST", "localhost"),
        "PORT": env("DB_PORT", "5432"),
        "CONN_MAX_AGE": 60,
        # Pooled connections (PgBouncer transaction mode: Neon "-pooler", Supabase "pooler") can't keep
        # server-side cursors open between queries; turned off automatically for such hosts.
        "DISABLE_SERVER_SIDE_CURSORS": env_bool("DB_DISABLE_SERVER_SIDE_CURSORS",
                                                "pooler" in env("DB_HOST", "localhost").lower()),
        "OPTIONS": {"sslmode": env("DB_SSLMODE", "prefer")},
    }
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Admins live in their own table, fully separate from students.
AUTH_USER_MODEL = "core.Admin"
LOGIN_URL = "dashboard:login"
LOGIN_REDIRECT_URL = "dashboard:home"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 12}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Rate limits must be shared by every app process: Redis when available; otherwise the
# database (DJANGO_CACHE=db, e.g. cPanel, after `manage.py createcachetable`); locmem for one process.
CACHES = {"default": (
    {"BACKEND": "django.core.cache.backends.redis.RedisCache", "LOCATION": env("REDIS_URL")}
    if env("REDIS_URL") else
    {"BACKEND": "django.core.cache.backends.db.DatabaseCache", "LOCATION": "ws_cache"}
    if env("DJANGO_CACHE") == "db" else
    {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}
)}

LANGUAGE_CODE = "en"
TIME_ZONE = "Asia/Dhaka"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    # Manifest storage adds a content hash to every file name (public.3f2a….css), so browsers load the new
    # CSS/JS right after an update instead of a cached copy. Run `collectstatic` after every upload.
    # (apps/core/storage.py falls back to the plain name if collectstatic was forgotten: no error 500.)
    "staticfiles": {"BACKEND": "apps.core.storage.ForgivingManifestStorage"
                    if not DEBUG else "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

# ---- Security (minors' personal data: secure by default)
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = 60 * 60 * 8
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SECURE_SSL_REDIRECT = env_bool("DJANGO_SSL_REDIRECT", not DEBUG)
SECURE_HSTS_SECONDS = 0 if DEBUG else 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEBUG
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
if env_bool("DJANGO_BEHIND_PROXY", False):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
TRUST_X_FORWARDED_FOR = env_bool("DJANGO_BEHIND_PROXY", False)

# ---- Email transport (vendor chosen by env: SES / Mailgun / Brevo all speak SMTP)
EMAIL_BACKEND = env("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
EMAIL_HOST = env("EMAIL_HOST", "")
EMAIL_PORT = int(env("EMAIL_PORT", "587"))
EMAIL_HOST_USER = env("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", "WikiScholar <no-reply@wikischolar.bd>")
# Email credentials entered on Dashboard -> Email settings override the values above.
# Their password is encrypted with this Fernet key (derived from SECRET_KEY when empty).
CREDENTIALS_KEY = env("WS_CREDENTIALS_KEY", "")

# ---- WikiScholar platform settings
WIKISCHOLAR = {
    "ID_PREFIX": env("WS_ID_PREFIX", "WS"),
    # Programme year in student IDs (WS-2027-000001). Set WS_ID_YEAR= (empty) to use the calendar year.
    "ID_YEAR": int(env("WS_ID_YEAR", "2027") or 0) or None,
    "CONTACT_EMAIL": env("WS_CONTACT_EMAIL", "info@wikischolar.bd"),
    # Where replies to every outgoing email go, unless Email settings has its own Reply-to.
    "REPLY_TO": env("WS_REPLY_TO", "info@wikischolar.bd"),
    # The programme's main website; the form's "Back to wikischolar.bd" link points here.
    "SITE_URL": env("WS_SITE_URL", "https://wikischolar.bd"),
    "POLICY_VERSION": env("WS_POLICY_VERSION", "2026-01"),
    "POLICY_URL": env("WS_POLICY_URL", "https://wikimedia.org.bd/youth-safety-policy"),
    "OTP_TTL_MINUTES": int(env("WS_OTP_TTL_MINUTES", "10")),
    "OTP_MAX_ATTEMPTS": int(env("WS_OTP_MAX_ATTEMPTS", "5")),
    "OTP_VERIFIED_WINDOW_MINUTES": int(env("WS_OTP_VERIFIED_WINDOW_MINUTES", "60")),
    # Dev-only convenience: echo OTP in API response. Ignored unless DEBUG is on.
    "OTP_DEBUG_ECHO": env_bool("WS_OTP_DEBUG_ECHO", False),
    "SCHOOL_AUTO_RESOLVE_THRESHOLD": float(env("WS_SCHOOL_AUTO_RESOLVE", "0.8")),
    "SCHOOL_DUPLICATE_THRESHOLD": float(env("WS_SCHOOL_DUPLICATE", "0.5")),
    "RATE_LIMITS": {  # (max hits, window seconds)
        "otp_per_email": (5, 3600),
        "otp_per_ip": (20, 3600),
        "register_per_ip": (15, 3600),
        "login_per_ip": (10, 900),
        "api_per_ip": (300, 300),
    },
    # Bulk sends up to this size start from the browser (sent in WS_INLINE_DISPATCH_SECONDS chunks, the
    # batch page continues automatically); bigger ones are left to the send_queued cron job.
    "INLINE_DISPATCH_MAX": int(env("WS_INLINE_DISPATCH_MAX", "300")),
    "INLINE_DISPATCH_SECONDS": int(env("WS_INLINE_DISPATCH_SECONDS", "20")),
}

NOTIFICATIONS = {
    "EMAIL_PROVIDER": env("NOTIFY_EMAIL_PROVIDER", "apps.notifications.providers.email.DjangoMailProvider"),
    "SMS_PROVIDER": env("NOTIFY_SMS_PROVIDER", "apps.notifications.providers.sms.ConsoleSmsProvider"),
    "SMS_API_URL": env("SMS_API_URL", ""),
    "SMS_USERNAME": env("SMS_USERNAME", ""),  # MiM SMS: panel login email
    "SMS_API_KEY": env("SMS_API_KEY", ""),
    "SMS_SENDER_ID": env("SMS_SENDER_ID", ""),
    "WEBHOOK_TOKEN": env("NOTIFY_WEBHOOK_TOKEN", ""),
}

# Everything goes to stderr: gunicorn/Docker logs, or stderr.log in the app folder on cPanel.
# django.request is included so 500 errors are logged with their traceback even when DEBUG is off.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
    "loggers": {
        "apps": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")},
        "django.request": {"handlers": ["console"], "level": "ERROR", "propagate": False},
    },
}
