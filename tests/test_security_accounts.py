"""Cloudflare Turnstile on "Send verification code" and the dashboard sign-in; admins changing passwords."""
from unittest import mock

from django.core import mail
from django.test import override_settings

from apps.core.models import Admin, AuditLog

from .base import WSTestCase
from .test_messaging import ws

ON = ws(TURNSTILE_SITE_KEY="1x00000000000000000000AA", TURNSTILE_SECRET_KEY="1x0000000000000000000000000000000AA")
PASS = mock.patch("apps.core.turnstile._siteverify", return_value={"success": True})
FAIL = mock.patch("apps.core.turnstile._siteverify", return_value={"success": False, "error-codes": ["invalid-input-response"]})
PASSWORD = "x-Strong-pass-123"


class TurnstileOffTests(WSTestCase):
    def test_no_widget_and_no_check_without_keys(self):
        page = self.client.get("/").content.decode()
        self.assertNotIn("challenges.cloudflare.com", page)
        self.client.get("/")
        r = self.post_json("/api/registration/email/send-otp/", {"email": "rahim@gmail.com"})
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("challenges.cloudflare.com", self.client.get("/dashboard/login/").content.decode())


@override_settings(WIKISCHOLAR=ON)
class TurnstileOnTests(WSTestCase):
    def send(self, **extra):
        self.client.get("/")
        return self.post_json("/api/registration/email/send-otp/", {"email": "rahim@gmail.com", **extra})

    def test_form_shows_the_widget(self):
        page = self.client.get("/").content.decode()
        self.assertIn('id="turnstile" data-sitekey="1x00000000000000000000AA"', page)
        self.assertIn("challenges.cloudflare.com/turnstile/v0/api.js?render=explicit", page)

    def test_send_code_needs_a_valid_token(self):
        r = self.send()
        self.assertEqual((r.status_code, r.json()["error"]), (400, "security_check"))
        with FAIL:
            self.assertEqual(self.send(turnstile_token="bad").json()["error"], "security_check")
        self.assertEqual(len(mail.outbox), 0)
        with PASS as verify:
            r = self.send(turnstile_token="good")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(verify.call_args[0][0], "good")
        self.assertEqual(len(mail.outbox), 1)

    def test_cloudflare_unreachable_fails_closed(self):
        with mock.patch("apps.core.turnstile._siteverify", side_effect=OSError("timeout")):
            self.assertEqual(self.send(turnstile_token="t").json()["error"], "security_check")

    def test_typo_hint_comes_before_the_check(self):
        # A typo answer sends nothing, so it doesn't need (or use up) the token
        self.client.get("/")
        r = self.post_json("/api/registration/email/send-otp/", {"email": "rahim@gmial.com"})
        self.assertEqual(r.json()["typo_suggestion"], "gmail.com")

    def test_dashboard_sign_in_needs_the_check(self):
        page = self.client.get("/dashboard/login/").content.decode()
        self.assertIn('class="cf-turnstile" data-sitekey="1x00000000000000000000AA"', page)
        r = self.client.post("/dashboard/login/", {"username": "admin@ws.test", "password": PASSWORD})
        self.assertContains(r, "Complete the security check")
        with PASS:
            r = self.client.post("/dashboard/login/", {"username": "admin@ws.test", "password": PASSWORD,
                                                       "cf-turnstile-response": "good"})
        self.assertEqual(r.status_code, 302)


class PasswordChangeTests(WSTestCase):
    def test_any_admin_changes_their_own_password(self):
        self.client.force_login(self.viewer)
        self.assertContains(self.client.get("/dashboard/"), "Change password")
        r = self.client.post("/dashboard/account/password/", {
            "old_password": "wrong", "new_password1": "New-strong-pass-456", "new_password2": "New-strong-pass-456"})
        self.assertIn("old_password", r.context["form"].errors)
        r = self.client.post("/dashboard/account/password/", {
            "old_password": PASSWORD, "new_password1": "short", "new_password2": "short"})
        self.assertIn("new_password2", r.context["form"].errors)
        r = self.client.post("/dashboard/account/password/", {
            "old_password": PASSWORD, "new_password1": "New-strong-pass-456", "new_password2": "New-strong-pass-456"})
        self.assertRedirects(r, "/dashboard/")
        self.assertEqual(self.client.get("/dashboard/").status_code, 200)  # still signed in
        self.assertTrue(Admin.objects.get(pk=self.viewer.pk).check_password("New-strong-pass-456"))
        log = AuditLog.objects.get(action="admin.password_changed")
        self.assertNotIn("password", str(log.before) + str(log.after) + str(log.meta))

    def test_sign_in_is_required(self):
        r = self.client.get("/dashboard/account/password/")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/dashboard/login/", r["Location"])

    def test_super_admin_sets_a_new_password_for_someone_else(self):
        self.client.force_login(self.super)
        self.assertContains(self.client.get("/dashboard/admins/"), "Set new password")
        r = self.client.post(f"/dashboard/admins/{self.admin.pk}/", {"op": "password", "password": "123"}, follow=True)
        self.assertContains(r, "not changed")
        self.assertTrue(Admin.objects.get(pk=self.admin.pk).check_password(PASSWORD))
        r = self.client.post(f"/dashboard/admins/{self.admin.pk}/", {"op": "password", "password": "Temp-pass-for-admin-789"},
                             follow=True)
        self.assertContains(r, "New password set for admin@ws.test")
        self.assertTrue(Admin.objects.get(pk=self.admin.pk).check_password("Temp-pass-for-admin-789"))
        self.assertTrue(AuditLog.objects.filter(action="admin.password_reset", entity_id=str(self.admin.pk)).exists())

    def test_only_super_admins_set_other_passwords(self):
        self.client.force_login(self.admin)
        r = self.client.post(f"/dashboard/admins/{self.viewer.pk}/", {"op": "password", "password": "Temp-pass-for-admin-789"})
        self.assertEqual(r.status_code, 403)
        self.assertTrue(Admin.objects.get(pk=self.viewer.pk).check_password(PASSWORD))


class WordingTests(WSTestCase):
    def test_section_says_if_any_and_banner_includes_leaflets(self):
        page = self.client.get("/").content.decode()
        self.assertIn('Section <span class="label-note">(if any)</span>', page)
        self.assertIn("শাখা (যদি থাকে)", page)
        self.assertIn("Banner / leaflet etc. · ব্যানার / লিফলেট ইত্যাদি", page)
