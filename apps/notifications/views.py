import json

from django.http import HttpResponseBadRequest, HttpResponseForbidden, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from . import services
from .models import Channel


@csrf_exempt
@require_POST
def delivery_webhook(request, channel):
    """Provider callback, ?token=NOTIFY_WEBHOOK_TOKEN. Accepts one event or a list, either
    {"message_id": "...", "status": "delivered|bounced|failed", "error": "..."} or Brevo's
    transactional webhook events ({"event": "delivered", "message-id": "<...>", ...})."""
    if channel not in Channel.values:
        return HttpResponseBadRequest("unknown channel")
    if not services.verify_webhook_token(request.GET.get("token", "")):
        return HttpResponseForbidden("bad token")
    try:
        payload = json.loads(request.body or b"{}")
    except ValueError:
        return HttpResponseBadRequest("invalid json")
    events = payload if isinstance(payload, list) else [payload]
    updated = sum(services.apply_delivery_event(channel, *services.normalize_event(e))
                  for e in events if isinstance(e, dict))
    return JsonResponse({"updated": updated})
