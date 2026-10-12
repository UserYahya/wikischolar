"""Public form header/links, school suggestions, reply-to, bulk sending and batch tracking."""
import io
import json
from unittest import mock

from django.conf import settings
from django.core import mail
from django.core.management import call_command
from django.test import override_settings

from apps.core.models import AuditLog
from apps.notifications import services as notify
from apps.notifications.models import EmailBatch, EmailSettings, NotificationLog
from apps.reference.models import School

from .base import WSTestCase


def ws(**over):
    return {**settings.WIKISCHOLAR, **over}


class PublicPageTests(WSTestCase):
    def test_header_has_logo_and_back_link_to_main_site(self):
        page = self.client.get("/").content.decode()
        self.assertIn('img/wikischolar-logo-en.png', page)
        self.assertNotIn('img/wikischolar-logo-bn.png', page)  # English logo only in the header
        self.assertIn('img/favicon-32.png', page)
        self.assertIn('alt="WikiScholar"', page)
        self.assertNotIn("Wiki<span>Scholar</span>", page)
        self.assertIn('href="https://wikischolar.bd"', page)
        self.assertIn("Back to wikischolar.bd", page)

    @override_settings(WIKISCHOLAR=ws(SITE_URL="https://example.org/"))
    def test_back_link_follows_setting(self):
        page = self.client.get("/").content.decode()
        self.assertIn('href="https://example.org"', page)
        self.assertIn("Back to example.org", page)

    def test_otp_is_email_only_and_mentions_spam(self):
        page = self.client.get("/").content.decode()
        self.assertIn("by email only", page)
        self.assertIn("Spam", page)

    def test_login_page_uses_logo(self):
        r = self.client.get("/dashboard/login/")
        self.assertContains(r, "img/wikischolar-logo-en.png")
        self.assertContains(r, "img/favicon-32.png")


class SchoolSuggestionTests(WSTestCase):
    def test_public_typeahead_suggests_only_approved_schools(self):
        School.objects.create(name="Tongi Pilot School", district=self.gazipur, thana=self.tongi,
                              verification_status="pending", source="registration")
        names = [s["name"] for s in self.client.get(
            "/api/reference/schools/", {"thana": self.tongi.pk, "q": "tongi"}).json()["schools"]]
        self.assertEqual(names, ["Tongi Government High School"])

    def test_suggestions_start_while_typing(self):
        for typed in ["ton", "tongi gov", "govt high", "high school"]:
            names = [s["name"] for s in self.client.get(
                "/api/reference/schools/", {"thana": self.tongi.pk, "q": typed}).json()["schools"]]
            self.assertIn("Tongi Government High School", names, typed)

    def test_dashboard_editor_still_lists_pending_schools(self):
        School.objects.create(name="Tongi Pilot School", district=self.gazipur, thana=self.tongi,
                              verification_status="pending", source="registration")
        self.client.force_login(self.admin)
        names = [s["name"] for s in self.client.get(
            "/api/reference/schools/", {"thana": self.tongi.pk, "all": 1}).json()["schools"]]
        self.assertEqual(sorted(names), ["Tongi Government High School", "Tongi Pilot School"])

    def test_approving_a_school_makes_it_suggested(self):
        pending = School.objects.create(name="Tongi Pilot School", district=self.gazipur, thana=self.tongi,
                                        verification_status="pending", source="registration")
        self.client.force_login(self.admin)
        self.client.post(f"/dashboard/schools/{pending.pk}/", {"op": "verify"})
        self.client.logout()
        names = [s["name"] for s in self.client.get(
            "/api/reference/schools/", {"thana": self.tongi.pk, "q": "pilot"}).json()["schools"]]
        self.assertEqual(names, ["Tongi Pilot School"])


class ReplyToTests(WSTestCase):
    def test_every_email_replies_to_info_by_default(self):
        s = self.register()  # OTP email (confirmation is sent on commit)
        self.assertEqual(mail.outbox[-1].reply_to, ["info@wikischolar.bd"])
        self.client.force_login(self.admin)
        mail.outbox.clear()
        self.client.post("/dashboard/messages/compose/", {
            "name": "Welcome", "channel": "email", "subject": "Hi", "body": "Hello {name}",
            "opted_in_only": "on", "confirm_count": 1})
        self.assertEqual([m.reply_to for m in mail.outbox], [["info@wikischolar.bd"]])
        self.assertTrue(s["wikischolar_id"])

    def test_confirmation_email_replies_to_info(self):
        vid = self.verify_email()
        mail.outbox.clear()
        with self.captureOnCommitCallbacks(execute=True):
            self.post_json("/api/registration/submit/", self.payload(vid))
        self.assertEqual(mail.outbox[-1].reply_to, ["info@wikischolar.bd"])

    def test_reply_to_from_email_settings_wins(self):
        self.client.force_login(self.super)
        page = self.client.get("/dashboard/settings/email/").content.decode()
        self.assertIn('value="info@wikischolar.bd"', page)  # pre-filled with the default
        self.client.post("/dashboard/settings/email/", {
            "op": "save", "provider": "console", "from_email": "noreply@wikimedia.org.bd", "from_name": "WS",
            "reply_to": "team@wikimedia.org.bd", "port": 587, "security": "starttls", "is_active": "on"})
        self.assertEqual(EmailSettings.active().reply_to, "team@wikimedia.org.bd")
        sent = []
        with mock.patch("django.core.mail.backends.console.EmailBackend.send_messages",
                        lambda backend, msgs: sent.extend(msgs) or len(msgs)):
            self.client.get("/")
            self.post_json("/api/registration/email/send-otp/", {"email": "rahim@gmail.com"})
        self.assertEqual(sent[-1].reply_to, ["team@wikimedia.org.bd"])

    @override_settings(WIKISCHOLAR=ws(REPLY_TO="replies@example.org"))
    def test_default_follows_setting(self):
        self.verify_email()
        self.assertEqual(mail.outbox[-1].reply_to, ["replies@example.org"])


class BulkSendingTests(WSTestCase):
    def setUp(self):
        super().setUp()
        self.ids = [self.register(email=f"s{i}@gmail.com")["wikischolar_id"] for i in range(3)]
        self.client.force_login(self.admin)
        mail.outbox.clear()

    def compose(self, **over):
        data = {"name": "Exam invite - Gazipur", "channel": "email", "subject": "Hi {name}",
                "body": "Dear {name}, your ID is {wikischolar_id}.", "opted_in_only": "on", "confirm_count": 3}
        data.update(over)
        return self.client.post("/dashboard/messages/compose/", data)

    def test_bulk_email_is_sent_named_and_personalised(self):
        r = self.compose()
        batch = EmailBatch.objects.get()
        self.assertRedirects(r, f"/dashboard/messages/{batch.batch_code}/", fetch_redirect_response=False)
        self.assertEqual((batch.name, batch.status, batch.recipient_count), ("Exam invite - Gazipur", "completed", 3))
        self.assertEqual(len(mail.outbox), 3)
        self.assertEqual(sorted(m.to[0] for m in mail.outbox), ["s0@gmail.com", "s1@gmail.com", "s2@gmail.com"])
        self.assertIn("Dear Rahim Uddin, your ID is WS-2027-", mail.outbox[0].body)
        self.assertEqual(set(batch.logs.values_list("status", flat=True)), {"sent"})

    def test_braces_in_the_message_do_not_break_sending(self):
        self.compose(body="Scores {50%} and a {typo} and {name}: see {https://x.org}", confirm_count=3)
        self.assertEqual(len(mail.outbox), 3)
        self.assertIn("{typo}", mail.outbox[0].body)
        self.assertIn("Rahim Uddin", mail.outbox[0].body)

    def test_name_is_required_and_english(self):
        r = self.compose(name="")
        self.assertIn("name", r.context["form"].errors)
        r = self.compose(name="পরীক্ষা")
        self.assertIn("name", r.context["form"].errors)
        self.assertFalse(EmailBatch.objects.exists())

    def test_zero_opted_in_explains_how_to_send(self):
        from apps.registration.models import Student
        Student.objects.update(updates_opt_in=False)
        r = self.client.get("/dashboard/messages/compose/")
        self.assertEqual(r.context["count"], 0)
        self.assertContains(r, "opted in to email updates")

    @override_settings(WIKISCHOLAR=ws(INLINE_DISPATCH_SECONDS=0))
    def test_sending_continues_in_chunks_until_done(self):
        r = self.compose()
        batch = EmailBatch.objects.get()
        self.assertEqual(r["Location"], f"/dashboard/messages/{batch.batch_code}/?continue=1")
        self.assertEqual(batch.logs.filter(status="queued").count(), 2)
        page = self.client.get(r["Location"])
        self.assertTrue(page.context["keep_sending"])
        self.assertContains(page, "sendRemaining")
        r = self.client.post(f"/dashboard/messages/{batch.batch_code}/send/")
        self.assertEqual(r["Location"], f"/dashboard/messages/{batch.batch_code}/?continue=1")
        r = self.client.post(f"/dashboard/messages/{batch.batch_code}/send/")
        self.assertEqual(r["Location"], f"/dashboard/messages/{batch.batch_code}/")
        batch.refresh_from_db()
        self.assertEqual(batch.status, "completed")
        self.assertEqual(len(mail.outbox), 3)

    @override_settings(WIKISCHOLAR=ws(INLINE_DISPATCH_MAX=1))
    def test_large_batch_is_queued_for_the_cron_job(self):
        self.compose()
        batch = EmailBatch.objects.get()
        self.assertEqual(batch.logs.filter(status="queued").count(), 3)
        self.assertEqual(len(mail.outbox), 0)
        out = io.StringIO()
        call_command("send_queued", stdout=out)
        self.assertIn(f"{batch.batch_code}: 0 still queued", out.getvalue())
        batch.refresh_from_db()
        self.assertEqual((batch.status, len(mail.outbox)), ("completed", 3))

    def test_nothing_is_sent_twice(self):
        self.compose()
        batch = EmailBatch.objects.get()
        self.assertEqual(notify.dispatch_batch(batch), 0)  # re-run: only queued rows are sent
        self.assertEqual(len(mail.outbox), 3)

    def test_provider_error_is_shown_and_recorded(self):
        from apps.notifications.providers.base import SendResult
        with mock.patch("apps.notifications.providers.email.DjangoMailProvider.send",
                        return_value=SendResult(ok=False, error="550 sender not verified")):
            r = self.compose()
        batch = EmailBatch.objects.get()
        self.assertEqual(set(batch.logs.values_list("status", flat=True)), {"failed"})
        flashes = [str(m) for m in r.wsgi_request._messages]
        self.assertTrue(any("3 failed" in m for m in flashes), flashes)
        self.assertTrue(any("550 sender not verified" in m for m in flashes), flashes)

    def test_brevo_api_message_id_is_stored_for_delivery_reports(self):
        self.client.force_login(self.super)
        self.client.post("/dashboard/settings/email/", {
            "op": "save", "provider": "brevo_api", "password": "xkeysib-abc", "from_email": "noreply@wikimedia.org.bd",
            "from_name": "WikiScholar", "reply_to": "", "port": 587, "security": "starttls", "is_active": "on"})
        with mock.patch("apps.notifications.backends.BrevoApiBackend._post",
                        side_effect=[{"messageId": f"<id{i}@smtp-relay.mailin.fr>"} for i in range(3)]) as post:
            self.compose()
        self.assertEqual(sorted(NotificationLog.objects.filter(kind="bulk").values_list("provider_message_id", flat=True)),
                         ["id0@smtp-relay.mailin.fr", "id1@smtp-relay.mailin.fr", "id2@smtp-relay.mailin.fr"])
        self.assertEqual(post.call_args.args[0]["replyTo"], {"email": "info@wikischolar.bd"})

    def test_works_without_server_side_cursors(self):
        """Pooled hosts (Neon "-pooler") need DISABLE_SERVER_SIDE_CURSORS; bulk sending must still work."""
        from django.db import connection
        with mock.patch.dict(connection.settings_dict, {"DISABLE_SERVER_SIDE_CURSORS": True}):
            self.compose()
            r = self.client.get(f"/dashboard/messages/{EmailBatch.objects.get().batch_code}/recipients.csv")
            self.assertEqual(b"".join(r.streaming_content).decode("utf-8-sig").count("@gmail.com"), 3)
        self.assertEqual(len(mail.outbox), 3)

    def test_pooled_host_turns_server_side_cursors_off(self):
        import importlib
        import os
        with mock.patch.dict(os.environ, {"DB_HOST": "ep-x-pooler.c-4.ap-southeast-1.aws.neon.tech"}):
            import config.settings as cfg
            importlib.reload(cfg)
            self.assertTrue(cfg.DATABASES["default"]["DISABLE_SERVER_SIDE_CURSORS"])
        importlib.reload(cfg)
        self.assertFalse(cfg.DATABASES["default"]["DISABLE_SERVER_SIDE_CURSORS"])


class BatchTrackingTests(WSTestCase):
    """Name batches, find them, see who got them and who didn't."""

    def setUp(self):
        super().setUp()
        self.ids = [self.register(email=f"t{i}@gmail.com")["wikischolar_id"] for i in range(3)]
        self.client.force_login(self.admin)
        self.client.post("/dashboard/messages/compose/", {
            "name": "Exam invite", "channel": "email", "subject": "Hi", "body": "Hello",
            "opted_in_only": "on", "confirm_count": 3})
        self.batch = EmailBatch.objects.get()
        self.bounced = self.batch.logs.get(wikischolar_id=self.ids[0])
        NotificationLog.objects.filter(pk=self.bounced.pk).update(status="bounced", error="mailbox full")

    def test_messages_list_search_and_problem_filter(self):
        self.client.post("/dashboard/messages/compose/", {
            "name": "Result notice", "channel": "sms", "body": "Results out", "confirm_count": 3})
        names = [b.name for b in self.client.get("/dashboard/messages/", {"q": "exam"}).context["batches"]]
        self.assertEqual(names, ["Exam invite"])
        names = [b.name for b in self.client.get("/dashboard/messages/", {"problems": "1"}).context["batches"]]
        self.assertEqual(names, ["Exam invite"])
        names = [b.name for b in self.client.get("/dashboard/messages/", {"channel": "sms"}).context["batches"]]
        self.assertEqual(names, ["Result notice"])
        page = self.client.get("/dashboard/messages/")
        self.assertContains(page, "?status=not_delivered")

    def test_batch_page_filters_not_delivered(self):
        url = f"/dashboard/messages/{self.batch.batch_code}/"
        r = self.client.get(url, {"status": "not_delivered"})
        self.assertEqual([l.wikischolar_id for l in r.context["page"]], [self.ids[0]])
        self.assertEqual(r.context["stats"]["not_delivered"], 1)
        r = self.client.get(url, {"status": "sent"})
        self.assertEqual(sorted(l.wikischolar_id for l in r.context["page"]), sorted(self.ids[1:]))
        r = self.client.get(url, {"q": self.ids[2]})
        self.assertEqual([l.wikischolar_id for l in r.context["page"]], [self.ids[2]])

    def test_recipients_csv_export_is_filtered_and_audited(self):
        r = self.client.get(f"/dashboard/messages/{self.batch.batch_code}/recipients.csv", {"status": "not_delivered"})
        body = b"".join(r.streaming_content).decode("utf-8-sig")
        self.assertIn("not_delivered", r["Content-Disposition"])
        self.assertIn(self.ids[0], body)
        self.assertIn("mailbox full", body)
        self.assertNotIn(self.ids[1], body)
        self.assertIn("Exam invite", body)
        self.assertTrue(AuditLog.objects.filter(action="messages.recipients_exported").exists())

    def test_students_filtered_by_message_history(self):
        from apps.registration.models import Student
        extra = self.register(email="late@gmail.com")["wikischolar_id"]  # registered after the batch
        code = self.batch.batch_code

        def ids(mode):
            r = self.client.get("/dashboard/students/", {"msg_batch": code, "msg_batch_mode": mode})
            return sorted(s.wikischolar_id for s in r.context["page"])
        self.assertEqual(ids("sent"), sorted(self.ids))
        self.assertEqual(ids("not_sent"), [extra])
        self.assertEqual(ids("not_delivered"), [self.ids[0]])
        # "not sent yet" + Message this group reaches exactly the missed student
        r = self.client.get("/dashboard/messages/compose/", {"msg_batch": code, "msg_batch_mode": "not_sent",
                                                            "opted_in_only": "0"})
        self.assertEqual(r.context["count"], 1)
        self.assertIn(("Message history", "Not sent: Exam invite"), r.context["filter_summary"])
        self.assertEqual(Student.objects.count(), 4)

    def test_resend_not_delivered(self):
        mail.outbox.clear()
        self.client.post(f"/dashboard/messages/{self.batch.batch_code}/resend/")
        retry = NotificationLog.objects.get(resend_of=self.bounced)
        self.assertEqual(retry.status, "sent")
        self.assertEqual([m.to for m in mail.outbox], [["t0@gmail.com"]])

    @override_settings(NOTIFICATIONS={**settings.NOTIFICATIONS, "WEBHOOK_TOKEN": "tok"})
    def test_brevo_webhook_marks_delivered_and_bounced(self):
        a, b = self.batch.logs.exclude(pk=self.bounced.pk).order_by("pk")
        NotificationLog.objects.filter(pk=a.pk).update(provider_message_id="m-a@wikimedia.org.bd")
        NotificationLog.objects.filter(pk=b.pk).update(provider_message_id="m-b@wikimedia.org.bd")
        for event, mid in [("delivered", "<m-a@wikimedia.org.bd>"), ("hard_bounce", "<m-b@wikimedia.org.bd>"),
                           ("opened", "<m-a@wikimedia.org.bd>")]:
            r = self.client.post("/notifications/webhook/email/?token=tok",
                                 json.dumps({"event": event, "email": "x@gmail.com", "message-id": mid,
                                             "reason": "user unknown" if event == "hard_bounce" else ""}),
                                 content_type="application/json")
            self.assertEqual(r.status_code, 200)
        a.refresh_from_db(), b.refresh_from_db()
        self.assertEqual((a.status, b.status, b.error), ("delivered", "bounced", "user unknown"))
        self.assertEqual(self.client.post("/notifications/webhook/email/?token=bad", "{}",
                                          content_type="application/json").status_code, 403)

    def test_batch_name_shown_on_student_page(self):
        self.assertContains(self.client.get(f"/dashboard/students/{self.ids[1]}/"), "Exam invite")
