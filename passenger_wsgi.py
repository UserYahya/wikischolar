"""Entry point for cPanel "Setup Python App" (Phusion Passenger). Settings come from .env
next to this file (see docs/DEPLOY_CPANEL.md) or from the app's environment variables."""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from django.core.wsgi import get_wsgi_application  # noqa: E402

application = get_wsgi_application()
