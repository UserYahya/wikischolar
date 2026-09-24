import json
import urllib.error
import urllib.request
from email.utils import parseaddr

from django.core.mail.backends.base import BaseEmailBackend


class BrevoApiBackend(BaseEmailBackend):
    """Django email backend that sends through Brevo's transactional HTTPS API (port 443), for hosts
    that block outgoing SMTP. https://developers.brevo.com/reference/sendtransacemail"""
    url = "https://api.brevo.com/v3/smtp/email"

    def __init__(self, api_key="", timeout=20, fail_silently=False, **kwargs):
        super().__init__(fail_silently=fail_silently, **kwargs)
        self.api_key, self.timeout = api_key, timeout

    def _payload(self, msg):
        name, addr = parseaddr(msg.from_email)
        payload = {"sender": {"email": addr, **({"name": name} if name else {})},
                   "to": [{"email": parseaddr(a)[1]} for a in msg.to],
                   "subject": msg.subject, "textContent": msg.body}
        if msg.cc:
            payload["cc"] = [{"email": parseaddr(a)[1]} for a in msg.cc]
        if msg.bcc:
            payload["bcc"] = [{"email": parseaddr(a)[1]} for a in msg.bcc]
        if msg.reply_to:
            payload["replyTo"] = {"email": parseaddr(msg.reply_to[0])[1]}
        for content, mimetype in getattr(msg, "alternatives", []) or []:
            if mimetype == "text/html":
                payload["htmlContent"] = content
        return payload

    def _post(self, payload):
        req = urllib.request.Request(self.url, data=json.dumps(payload).encode(), method="POST", headers={
            "api-key": self.api_key, "Content-Type": "application/json", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read() or b"{}")
        except urllib.error.HTTPError as exc:  # surface Brevo's own message (bad key, unverified sender...)
            try:
                detail = json.loads(exc.read()).get("message", "")
            except (ValueError, AttributeError):
                detail = ""
            raise RuntimeError(f"Brevo API error {exc.code}: {detail or exc.reason}") from exc

    def send_messages(self, email_messages):
        sent = 0
        for msg in email_messages:
            if not msg.recipients():
                continue
            try:
                reply = self._post(self._payload(msg))
            except Exception:
                if not self.fail_silently:
                    raise
                continue
            # Brevo's own ID, e.g. "<2026...@smtp-relay.mailin.fr>": its delivery webhooks refer to it
            msg.provider_message_id = str((reply or {}).get("messageId", ""))
            sent += 1
        return sent
