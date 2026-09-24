import csv

from django.conf import settings
from django.contrib import messages
from django.db.models import Q
from django.http import Http404, StreamingHttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.core import audit
from apps.core.permissions import require_perm
from apps.notifications import services as notify
from apps.notifications.models import Channel, NotificationLog

from .. import filters
from ..forms import ComposeForm
from ._util import paginate

# Recipient filter on a batch page: a delivery status, or "not_delivered" (failed + bounced).
NOT_DELIVERED = "not_delivered"


def _get_batch(code):
    batch = notify.get_batch(code)
    if not batch:
        raise Http404
    return batch


def _batch_url(batch, keep_sending=False):
    return reverse("dashboard:batch", kwargs={"code": batch.batch_code}) + ("?continue=1" if keep_sending else "")


def _report(request, batch, remaining):
    """One flash message with what happened, plus the first provider error if anything failed."""
    stats = notify.batch_stats(batch)
    sent = stats["sent"] + stats["delivered"]
    text = f"“{batch.label}” ({batch.batch_code}): {sent} sent"
    if stats["not_delivered"]:
        text += f", {stats['not_delivered']} failed"
    if remaining:
        text += f", {remaining} still to send (sending continues on this page)"
    (messages.warning if stats["not_delivered"] else messages.success)(request, text + ".")
    if stats["not_delivered"]:
        error = (batch.logs.filter(status__in=NotificationLog.NOT_DELIVERED).exclude(error="")
                 .values_list("error", flat=True).first())
        if error:
            hint = ""
            if "535" in error or "uthentication" in error or "401" in error:
                hint = (" The email provider refused the login: check the username and password / key on "
                        "Email & SMS settings (for Brevo SMTP use the SMTP login and an SMTP key; for the Brevo API "
                        "an API key), then send a test email.")
            messages.error(request, f"Provider error: {error}{hint}")


@require_perm("messages.view")
def batch_list(request):
    f = {"q": request.GET.get("q", "").strip(), "channel": request.GET.get("channel", ""),
         "problems": request.GET.get("problems") == "1"}
    if f["channel"] not in Channel.values:
        f["channel"] = ""
    return render(request, "dashboard/batches.html", {
        "batches": notify.find_batches(q=f["q"], channel=f["channel"], problems=f["problems"]), "f": f,
        "channels": Channel.choices})


@require_perm("messages.send")
def compose(request):
    source = request.POST if request.method == "POST" else request.GET
    p = filters.params_from(source)
    base = filters.apply(p)
    form = ComposeForm(request.POST or None, initial={"channel": Channel.EMAIL, "opted_in_only": True})
    if request.method == "POST":
        channel, opted = request.POST.get("channel") or Channel.EMAIL, request.POST.get("opted_in_only") == "on"
    else:
        channel, opted = request.GET.get("channel") or Channel.EMAIL, request.GET.get("opted_in_only", "1") != "0"
    if channel not in Channel.values:
        channel = Channel.EMAIL
    recipients = base.filter(updates_opt_in=True) if (channel == Channel.EMAIL and opted) else base
    count = recipients.count()
    if request.method == "POST" and form.is_valid():
        if form.cleaned_data["confirm_count"] != count:
            messages.error(request, f"The recipient count changed to {count}. Review and send again.")
        elif count == 0:
            messages.error(request, "No recipients match this filter.")
        else:
            d = form.cleaned_data
            batch = notify.create_batch(channel=d["channel"], students=recipients, body=d["body"],
                                        subject=d.get("subject", ""), name=d["name"],
                                        filter_snapshot=filters.snapshot(p),
                                        opted_in_only=d["channel"] == Channel.EMAIL and d["opted_in_only"],
                                        request=request)
            if count <= settings.WIKISCHOLAR["INLINE_DISPATCH_MAX"]:
                remaining = notify.dispatch_batch(batch, time_limit=settings.WIKISCHOLAR["INLINE_DISPATCH_SECONDS"])
                _report(request, batch, remaining)
                return redirect(_batch_url(batch, keep_sending=bool(remaining)))
            messages.success(request, f"“{batch.label}” ({batch.batch_code}) queued for {count} recipients. "
                                      "The send_queued job delivers it; you can also send it from this page.")
            return redirect(_batch_url(batch))
    return render(request, "dashboard/compose.html", {
        "form": form, "p": p, "hidden": [(k, v) for k, vals in filters.snapshot(p).items()
                                         for v in (vals if isinstance(vals, list) else [vals])],
        "count": count, "total_in_filter": base.count(), "channel": channel, "opted": opted,
        "filter_summary": filters.describe(filters.snapshot(p)),
    })


def _recipients(request, batch):
    """The batch's recipient rows, filtered by ?status= (incl. not_delivered) and ?q=."""
    status, q = request.GET.get("status", ""), request.GET.get("q", "").strip()
    logs = batch.logs.select_related("student").order_by("-created_at", "-id")
    if status == NOT_DELIVERED:
        logs = logs.filter(status__in=NotificationLog.NOT_DELIVERED)
    elif status in NotificationLog.Status.values:
        logs = logs.filter(status=status)
    else:
        status = ""
    if q:
        logs = logs.filter(Q(wikischolar_id__iexact=q) | Q(destination__icontains=q)
                           | Q(student__student_name__icontains=q))
    return logs, status, q


@require_perm("messages.view")
def batch_detail(request, code):
    batch = _get_batch(code)
    logs, status, q = _recipients(request, batch)
    page, qstring = paginate(request, logs, 100)
    stats = notify.batch_stats(batch)
    return render(request, "dashboard/batch_detail.html", {
        "batch": batch, "stats": stats, "page": page, "qstring": qstring, "status": status, "q": q,
        "statuses": NotificationLog.Status.choices, "not_delivered": NOT_DELIVERED,
        "filter_summary": filters.describe(batch.filter_snapshot),
        "failed": batch.logs.filter(status__in=NotificationLog.NOT_DELIVERED, resends__isnull=True).count(),
        "keep_sending": request.GET.get("continue") == "1" and stats["queued"] > 0,
        "can_send": request.user.has_perm_code("messages.send"),
    })


class _Echo:
    def write(self, value):
        return value


@require_perm("messages.view")
def batch_recipients_csv(request, code):
    batch = _get_batch(code)
    logs, status, q = _recipients(request, batch)
    audit.record("messages.recipients_exported", request=request, entity=batch,
                 meta={"status": status, "q": q, "rows": logs.count()})
    writer = csv.writer(_Echo())

    def rows():
        yield "﻿"  # BOM so Excel reads names correctly
        yield writer.writerow(["batch_code", "batch_name", "wikischolar_id", "student_name", "sent_to", "status",
                               "attempts", "error", "sent_at", "status_updated_at", "resend"])
        for log in logs.iterator(chunk_size=500):
            yield writer.writerow([batch.batch_code, batch.name, log.wikischolar_id,
                                   log.student.student_name if log.student else "", log.destination, log.status,
                                   log.attempts, log.error, log.sent_at.isoformat() if log.sent_at else "",
                                   log.status_updated_at.isoformat() if log.status_updated_at else "",
                                   "yes" if log.resend_of_id else ""])

    resp = StreamingHttpResponse(rows(), content_type="text/csv; charset=utf-8")
    suffix = f"-{status}" if status else ""
    resp["Content-Disposition"] = f'attachment; filename="{batch.batch_code}-recipients{suffix}.csv"'
    return resp


@require_POST
@require_perm("messages.send")
def send_remaining(request, code):
    """Send the next chunk of queued messages (the batch page calls this repeatedly until done)."""
    batch = _get_batch(code)
    remaining = notify.dispatch_batch(batch, time_limit=settings.WIKISCHOLAR["INLINE_DISPATCH_SECONDS"])
    _report(request, batch, remaining)
    return redirect(_batch_url(batch, keep_sending=bool(remaining)))


@require_POST
@require_perm("messages.send")
def resend_failed(request, code):
    batch = _get_batch(code)
    new_logs = notify.queue_resend_failed(batch, request=request)
    count = new_logs.count()
    remaining = notify.dispatch_batch(batch, only_logs=new_logs,
                                      time_limit=settings.WIKISCHOLAR["INLINE_DISPATCH_SECONDS"])
    messages.success(request, f"Resending {count} message(s).")
    _report(request, batch, remaining)
    return redirect(_batch_url(batch, keep_sending=bool(remaining)))
