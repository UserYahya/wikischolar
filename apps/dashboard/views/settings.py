from django.conf import settings
from django.contrib import messages
from django.db import transaction
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone

from apps.core import audit
from apps.core.permissions import require_perm
from apps.notifications import services as notify
from apps.notifications.models import EmailSettings, SmsSettings

from ..forms import EmailSettingsForm, SmsSettingsForm, SystemEmailForm, TestEmailForm, TestSmsForm


def _row(model):
    """The single settings row (pk=1), unsaved when nothing has been stored yet."""
    obj = model.objects.filter(pk=1).first() or model(pk=1)
    return obj, not obj._state.adding


def _save(request, form, before, action, secret_field):
    with transaction.atomic():
        obj = form.save(commit=False)
        obj.updated_by, obj.updated_at = request.user, timezone.now()
        obj.save()
        audit.record(action, request=request, entity=obj, before=before, after=obj.audit_view(),
                     meta={f"{secret_field}_changed": bool(form.cleaned_data.get(secret_field))})
    return obj


@require_perm("settings.manage")
def email_settings(request):
    """Email and SMS delivery credentials (one page; each form posts its own `op`)."""
    op = request.POST.get("op", "") if request.method == "POST" else ""
    email_cfg, email_saved = _row(EmailSettings)
    sms_cfg, sms_saved = _row(SmsSettings)
    email_before = email_cfg.audit_view() if email_saved else None
    sms_before = sms_cfg.audit_view() if sms_saved else None

    default_reply_to = settings.WIKISCHOLAR["REPLY_TO"]
    form = EmailSettingsForm(request.POST if op == "save" else None, instance=email_cfg,
                             initial={} if email_cfg.reply_to else {"reply_to": default_reply_to})
    test_form = TestEmailForm(request.POST if op == "test" else None, initial={"to": request.user.email})
    sms_form = SmsSettingsForm(request.POST if op == "sms_save" else None, instance=sms_cfg)
    sms_test_form = TestSmsForm(request.POST if op == "sms_test" else None)

    # ---- email ----
    if op == "save" and form.is_valid():
        obj = _save(request, form, email_before, "settings.email_updated", "password")
        messages.success(request, "Email settings saved." + ("" if obj.is_active else
                         " They are not active yet: tick “Use these settings” when the test email works."))
        return redirect("dashboard:email_settings")
    if op == "test" and test_form.is_valid():
        to = test_form.cleaned_data["to"]
        if not email_saved:
            messages.error(request, "Save the email settings first, then send a test email.")
        else:
            result = notify.send_test_email(email_cfg, to)
            audit.record("settings.email_tested", request=request, entity=email_cfg,
                         meta={"to": to, "ok": result.ok, "error": result.error})
            if result.ok:
                messages.success(request, f"Test email sent to {to}. Check the inbox (and the spam folder).")
            else:
                messages.error(request, f"Sending failed: {result.error}")
        return redirect("dashboard:email_settings")

    # ---- SMS ----
    if op == "sms_save" and sms_form.is_valid():
        obj = _save(request, sms_form, sms_before, "settings.sms_updated", "api_key")
        messages.success(request, "SMS settings saved." + ("" if obj.is_active else
                         " They are not active yet: tick “Use these settings” when the test SMS works."))
        return redirect("dashboard:email_settings")
    if op == "sms_test" and sms_test_form.is_valid():
        phone = sms_test_form.cleaned_data["phone"]
        if not sms_saved:
            messages.error(request, "Save the SMS settings first, then send a test SMS.")
        else:
            result = notify.send_test_sms(sms_cfg, phone)
            audit.record("settings.sms_tested", request=request, entity=sms_cfg,
                         meta={"to": phone, "ok": result.ok, "error": result.error})
            if result.ok:
                messages.success(request, f"Test SMS sent to {phone} (tracking ID {result.provider_message_id or '—'}).")
            else:
                messages.error(request, f"Sending failed: {result.error}")
        return redirect("dashboard:email_settings")
    if op == "sms_balance":
        provider = sms_cfg.provider_instance() if sms_saved else None
        if not hasattr(provider, "balance"):
            messages.error(request, "Save MiM SMS settings first to check the balance.")
        else:
            ok, value = provider.balance()
            (messages.success if ok else messages.error)(
                request, f"MiM SMS balance: {value}" if ok else f"Balance check failed: {value}")
        return redirect("dashboard:email_settings")

    return render(request, "dashboard/email_settings.html", {
        "form": form, "test_form": test_form, "cfg": email_cfg if email_saved else None,
        "email": notify.email_delivery(), "default_reply_to": default_reply_to,
        "sms_form": sms_form, "sms_test_form": sms_test_form, "sms_cfg": sms_cfg if sms_saved else None,
        "sms": notify.sms_delivery(),
    })


@require_perm("settings.manage")
def system_emails(request):
    """Edit the wording of system emails (OTP, registration confirmation, …) registered by the modules."""
    op, key = request.POST.get("op", ""), request.POST.get("key", "")
    cards = []
    for email in notify.system_emails():
        subject, body, row = notify.system_email_text(email.key)
        bound = request.method == "POST" and op == "save" and key == email.key
        form = SystemEmailForm(request.POST if bound else None, email=email,
                               initial={"subject": subject, "body": body})
        if bound and form.is_valid():
            notify.save_system_email(email.key, form.cleaned_data["subject"], form.cleaned_data["body"],
                                     request=request)
            messages.success(request, f"Saved “{email.label}”. It is used from now on.")
            return redirect(f"{reverse('dashboard:system_emails')}#{email.key}")
        preview_subject, preview_body = notify.render_system_email(email.key, email.sample)
        cards.append({"email": email, "form": form, "row": row, "customized": bool(row and row.is_customized),
                      "preview_subject": preview_subject, "preview_body": preview_body})

    if request.method == "POST" and op in ("reset", "test"):
        email = next((e for e in notify.system_emails() if e.key == key), None)
        if email is None:
            messages.error(request, "Unknown email.")
        elif op == "reset":
            if notify.reset_system_email(key, request=request):
                messages.success(request, f"“{email.label}” is back to the default text.")
            else:
                messages.info(request, f"“{email.label}” already uses the default text.")
        else:
            result = notify.send_system_email_test(key, request.user.email, request=request)
            if result.ok:
                messages.success(request, f"Test of “{email.label}” sent to {request.user.email} (with sample data).")
            else:
                messages.error(request, f"Sending failed: {result.error}")
        return redirect(f"{reverse('dashboard:system_emails')}#{key}")

    return render(request, "dashboard/system_emails.html", {"cards": cards, "email": notify.email_delivery()})
