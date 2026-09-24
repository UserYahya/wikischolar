import json

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from apps.core import ratelimit
from apps.core.utils import client_ip

from . import services
from .choices import CLASS_CHOICES, Gender, GuardianRelation
from .forms import RegistrationForm
from .validators import suggest_email_domain

SESSION_KEY = "ws_email_verifications"
MESSAGES = {
    "rate_limited": "Too many attempts. Please wait a while and try again.",
    "invalid_email": "Enter a valid email address.",
    "wrong_code": "That code doesn't match. Check it and try again.",
    "expired": "This code has expired. Send a new one.",
    "locked": "Too many wrong codes. Send a new one.",
    "not_found": "Verification session not found. Send a new code.",
    "email_not_verified": "Your email isn't verified, or the verification expired. Please verify again.",
    "send_failed": "We couldn't send the code. Check the email address and try again.",
    "email_taken": services.EMAIL_TAKEN_MESSAGE,
}


def _json(request):
    try:
        return json.loads(request.body or b"{}")
    except ValueError:
        return {}


def _err(code, status=400, **extra):
    return JsonResponse({"error": code, "message": MESSAGES.get(code, code), **extra}, status=status)


@require_GET
@ensure_csrf_cookie
def register_page(request):
    return render(request, "registration/register.html", {
        "genders": Gender.choices, "relations": GuardianRelation.choices, "classes": CLASS_CHOICES,
        "otp_ttl": settings.WIKISCHOLAR["OTP_TTL_MINUTES"],
    })


def _typo(email):
    """{typo_suggestion, suggested_email, message} when the domain looks mistyped, else {}."""
    suggestion = suggest_email_domain(email)
    if not suggestion:
        return {}
    local = email.rsplit("@", 1)[0]
    return {"typo_suggestion": suggestion, "suggested_email": f"{local}@{suggestion}",
            "message": f"Did you mean {local}@{suggestion}?"}


@require_GET
def check_email(request):
    """Instant typo hint while the user types; sends nothing and stores nothing."""
    return JsonResponse(_typo(request.GET.get("email", "").strip().lower()[:254]))


@require_POST
def send_otp(request):
    data = _json(request)
    email = str(data.get("email", "")).strip().lower()
    # Typos first: "name@gmailcom" is invalid, but the useful answer is the suggestion.
    if not data.get("confirm_typo") and (typo := _typo(email)):
        return JsonResponse(typo)
    try:
        validate_email(email)
        if not email.isascii():
            raise ValidationError("not ascii")
    except ValidationError:
        return _err("invalid_email")
    ip = client_ip(request) or "unknown"
    if not (ratelimit.allow("otp_per_ip", ip) and ratelimit.allow("otp_per_email", email)):
        return _err("rate_limited", 429)
    # One email per student: refuse before sending a code (checked after the rate limit, so the
    # form can't be used to test many addresses quickly).
    if services.email_registered(email):
        return _err("email_taken", 409)
    ev, code, log = services.start_email_verification(email, request=request)
    if log.status == "failed":
        return _err("send_failed", 502)
    request.session[SESSION_KEY] = (request.session.get(SESSION_KEY, []) + [str(ev.id)])[-5:]
    resp = {"verification_id": str(ev.id), "expires_in_minutes": settings.WIKISCHOLAR["OTP_TTL_MINUTES"]}
    if settings.DEBUG and settings.WIKISCHOLAR["OTP_DEBUG_ECHO"]:
        resp["debug_code"] = code
    return JsonResponse(resp)


@require_POST
def verify_otp(request):
    data = _json(request)
    vid, code = str(data.get("verification_id", "")), str(data.get("code", ""))
    if vid not in request.session.get(SESSION_KEY, []):
        return _err("not_found")
    with transaction.atomic():
        ok, error = services.check_email_code(vid, code)
    return JsonResponse({"verified": True}) if ok else _err(error)


@require_POST
def submit(request):
    if not ratelimit.allow("register_per_ip", client_ip(request) or "unknown"):
        return _err("rate_limited", 429)
    form = RegistrationForm(_json(request))
    if not form.is_valid():
        if "website" in form.errors:  # honeypot: pretend success, store nothing
            return JsonResponse({"error": "rejected"}, status=400)
        return JsonResponse({"error": "validation", "errors": form.errors}, status=400)
    if str(form.cleaned_data["verification_id"]) not in request.session.get(SESSION_KEY, []):
        return _err("email_not_verified")
    try:
        student = services.register_student(form.cleaned_data, request=request)
    except ValueError as exc:
        return _err(str(exc))
    request.session[SESSION_KEY] = []
    return JsonResponse({"ok": True, "summary": services.summary(student)}, status=201)
