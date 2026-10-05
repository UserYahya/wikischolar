"""
Cloudflare Turnstile: a privacy-friendly "are you human" check (usually invisible, at most one click).

Used before "Send verification code" on the public form (each code is a real email, the main
abuse target) and on the dashboard sign-in. It is on only when both keys are set
(WS_TURNSTILE_SITE_KEY and WS_TURNSTILE_SECRET_KEY, from the Cloudflare dashboard → Turnstile);
otherwise every check passes and no widget is shown.
https://developers.cloudflare.com/turnstile/get-started/server-side-validation/
"""
import json
import logging
import urllib.parse
import urllib.request

from django.conf import settings

VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
SCRIPT_URL = "https://challenges.cloudflare.com/turnstile/v0/api.js"
TOKEN_FIELD = "cf-turnstile-response"  # the hidden input the widget adds to a normal <form>
log = logging.getLogger(__name__)


def site_key():
    """The public site key while Turnstile is on, else ""."""
    ws = settings.WIKISCHOLAR
    return ws["TURNSTILE_SITE_KEY"] if ws["TURNSTILE_SITE_KEY"] and ws["TURNSTILE_SECRET_KEY"] else ""


def enabled():
    return bool(site_key())


def _siteverify(token, ip):
    fields = {"secret": settings.WIKISCHOLAR["TURNSTILE_SECRET_KEY"], "response": token}
    if ip:
        fields["remoteip"] = ip
    req = urllib.request.Request(VERIFY_URL, data=urllib.parse.urlencode(fields).encode(), method="POST")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read() or b"{}")


def verify(token, ip=None):
    """True when Turnstile is off, or Cloudflare confirms the token (each token works once, for 5 minutes).
    If Cloudflare can't be reached the check fails (the person can simply try again)."""
    if not enabled():
        return True
    if not token or len(token) > 2048:
        return False
    try:
        result = _siteverify(token, ip)
    except Exception as exc:  # network trouble, bad secret, ...
        log.warning("Turnstile verification could not be completed: %s", exc)
        return False
    if not result.get("success"):
        log.info("Turnstile refused a token: %s", result.get("error-codes"))
    return bool(result.get("success"))
