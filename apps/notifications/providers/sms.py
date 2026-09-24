import json
import logging
import urllib.parse
import urllib.request
import uuid

from django.conf import settings

from .base import Provider, SendResult

log = logging.getLogger("apps.notifications.sms")


class ConsoleSmsProvider(Provider):
    """Development provider: prints SMS to the log."""
    name = "console-sms"

    def send(self, destination, body, subject=""):
        mid = uuid.uuid4().hex
        log.info("SMS to %s [%s]: %s", destination, mid, body)
        return SendResult(ok=True, provider_message_id=mid)


class MimSmsProvider(Provider):
    """
    MiM SMS API v2 (https://www.mimsms.com/api-documentation).
    Sends each message as a transactional SMS (POST {api_url}/V2/SMS, transactionType "T"):
    one recipient per call, which gives every student its own trackingId for delivery reports.
    Unicode (Bangla) is detected by the gateway. The server's IP and domain must be whitelisted
    in the MiM SMS panel (Utility -> Developer) or every call is rejected.
    Credentials come from Dashboard -> Email & SMS settings, or from env via NOTIFY_SMS_PROVIDER.
    """
    name = "mimsms"
    timeout = 20

    def __init__(self, api_url=None, username=None, api_key=None, sender_name=None):
        cfg = settings.NOTIFICATIONS
        self.api_url = (api_url or cfg.get("SMS_API_URL") or "https://api.mimsms.com/api").rstrip("/")
        self.username = username if username is not None else cfg.get("SMS_USERNAME", "")
        self.api_key = api_key if api_key is not None else cfg.get("SMS_API_KEY", "")
        self.sender_name = sender_name if sender_name is not None else cfg.get("SMS_SENDER_ID", "")

    def _post(self, path, payload):
        req = urllib.request.Request(f"{self.api_url}{path}", data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json", "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
        try:
            return json.loads(raw or "{}"), raw
        except ValueError:
            return {}, raw

    @staticmethod
    def _error(data, raw):
        errors = [e.get("error") for e in (data.get("error_Data") or []) if isinstance(e, dict) and e.get("error")]
        reason = "; ".join(errors) or data.get("responseResult") or raw
        return f"MiM SMS {data.get('statusCode') or '?'}: {reason}"[:500]

    def send(self, destination, body, subject=""):
        if not (self.username and self.api_key and self.sender_name):
            return SendResult(ok=False, error="MiM SMS username, API key and sender ID are required")
        payload = {"userName": self.username, "apiKey": self.api_key, "senderName": self.sender_name,
                   "transactionType": "T", "campaignName": "WikiScholar",
                   "mobileNumber": "88" + destination, "message": body}
        try:
            data, raw = self._post("/V2/SMS", payload)
        except Exception as exc:  # network, TLS, HTTP errors
            return SendResult(ok=False, error=f"MiM SMS request failed: {exc}"[:500])
        if str(data.get("statusCode")) == "200" and str(data.get("status", "")).lower() == "success":
            sent = (data.get("success_Data") or [{}])[0] or {}
            return SendResult(ok=True, provider_message_id=str(sent.get("trackingId") or data.get("trxnId") or ""))
        return SendResult(ok=False, error=self._error(data, raw))

    def balance(self):
        """(ok, balance_or_error). POST /V2/BalanceCheck; the balance is in responseResult."""
        if not (self.username and self.api_key):
            return False, "Username and API key are required"
        try:
            data, raw = self._post("/V2/BalanceCheck", {"userName": self.username, "apiKey": self.api_key})
        except Exception as exc:
            return False, f"MiM SMS request failed: {exc}"[:500]
        if str(data.get("statusCode")) == "200":
            return True, str(data.get("responseResult", ""))
        return False, self._error(data, raw)

    def delivery_status(self, destination, tracking_id):
        """(ok, operator_status_or_error). POST /V2/DlrApi; available ~5 minutes after sending."""
        try:
            data, raw = self._post("/V2/DlrApi", {"userName": self.username, "apiKey": self.api_key,
                                                  "mobileNumber": "88" + destination, "trackingId": tracking_id})
        except Exception as exc:
            return False, f"MiM SMS request failed: {exc}"[:500]
        if str(data.get("statusCode")) == "200":
            return True, str(data.get("operatorStatus", ""))
        return False, self._error(data, raw)


class HttpSmsProvider(Provider):
    """
    Generic form-encoded HTTP gateway adapter for other BD gateways (MiM SMS: use MimSmsProvider).
    Configure SMS_API_URL / SMS_API_KEY / SMS_SENDER_ID. Adjust `_payload`
    and `_parse` once the vendor's exact API contract is finalised.
    """
    name = "http-sms"
    timeout = 15

    def _payload(self, destination, body):
        cfg = settings.NOTIFICATIONS
        return {"api_key": cfg["SMS_API_KEY"], "senderid": cfg["SMS_SENDER_ID"],
                "number": "88" + destination, "message": body, "type": "unicode"}

    def _parse(self, raw):
        data = json.loads(raw or "{}")
        ok = str(data.get("status", data.get("response_code", ""))).lower() in ("success", "202", "200", "ok")
        return SendResult(ok=ok, provider_message_id=str(data.get("message_id", data.get("trxnId", ""))),
                          error="" if ok else raw[:500])

    def send(self, destination, body, subject=""):
        url = settings.NOTIFICATIONS["SMS_API_URL"]
        if not url:
            return SendResult(ok=False, error="SMS_API_URL is not configured")
        data = urllib.parse.urlencode(self._payload(destination, body)).encode()
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=self.timeout) as resp:
                return self._parse(resp.read().decode("utf-8", "replace"))
        except Exception as exc:
            return SendResult(ok=False, error=str(exc)[:500])
