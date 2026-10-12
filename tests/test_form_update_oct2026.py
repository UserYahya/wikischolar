"""October 2026 form update: Bangla beside the English, section, numbers-only roll, the "how did you hear"
survey, no date of birth, the new Youth Policy link, HTML emails and grouped dashboard navigation."""
import re

from django.core import mail
from django.test import override_settings

from apps.core.registry import nav_groups_for
from apps.notifications import html_email
from apps.registration import bangla, forms, views
from apps.registration.choices import HeardFrom
from apps.registration.models import Student
from apps.registration.services import EMAIL_TAKEN_MESSAGE

from .base import WSTestCase
from .test_messaging import ws


class FormFieldTests(WSTestCase):
    def test_section_is_optional_and_saved_in_english(self):
        s = self.register(section="B")
        self.assertEqual(s["section"], "B")
        self.assertEqual(Student.objects.get(wikischolar_id=s["wikischolar_id"]).section, "B")
        s = self.register(email="nosection@gmail.com", section="")
        self.assertEqual(Student.objects.get(wikischolar_id=s["wikischolar_id"]).section, "")
        vid = self.verify_email("bn@gmail.com")
        r = self.post_json("/api/registration/submit/", self.payload(vid, email="bn@gmail.com", section="ক"))
        self.assertIn("English", r.json()["errors"]["section"][0])

    def test_class_roll_is_numbers_only(self):
        vid = self.verify_email()
        for bad in ["12A", "১২ক", "12-B", "roll 5"]:
            r = self.post_json("/api/registration/submit/", self.payload(vid, class_roll=bad))
            self.assertEqual(r.json()["errors"]["class_roll"],
                             ["Write the class roll in numbers only (for example 12)."], bad)
        s = self.register(class_roll="০৭")
        self.assertEqual(s["class_roll"], "07")

    def test_heard_from_is_required_and_stored(self):
        vid = self.verify_email()
        for bad in ["", "tv"]:
            r = self.post_json("/api/registration/submit/", self.payload(vid, heard_from=bad))
            self.assertEqual(r.json()["errors"]["heard_from"], ["Choose how you heard about WikiScholar."], bad)
        s = self.register(heard_from=HeardFrom.VOLUNTEERS)
        self.assertEqual(s["heard_from"], "Wikipedia volunteers came to our school")
        self.assertEqual(Student.objects.get(wikischolar_id=s["wikischolar_id"]).heard_from, "volunteers")

    def test_survey_lists_all_seven_options(self):
        page = self.client.get("/").content.decode()
        for label in ["Social media", "Google or YouTube ad", "Notice on Wikipedia", "Teacher or school announcement",
                      "Banner", "Wikipedia volunteers came to our school", "Somewhere else"]:
            self.assertIn(label, page)
        self.assertLess(page.index('name="heard_from"'), page.index('name="policy_consent"'))

    def test_favicon_ico_redirects_to_the_site_icon(self):
        r = self.client.get("/favicon.ico")
        self.assertEqual(r.status_code, 302)
        self.assertIn("img/favicon-32.png", r["Location"])

    def test_success_screen_has_print_and_back_buttons(self):
        page = self.client.get("/").content.decode()
        self.assertIn('id="printDone"', page)
        self.assertIn("Print / Save as PDF", page)
        self.assertIn('<a class="btn quiet" href="https://wikischolar.bd">', page)
        css = open("static/css/public.css", encoding="utf-8").read()
        self.assertIn("@media print", css)
        self.assertNotIn("border-top: 6px solid", css)  # no coloured strip on the success card

    def test_summary_has_registration_date(self):
        s = self.register()
        self.assertRegex(s["registered_on"], r"^\d{2}/\d{2}/\d{4}$")

    def test_policy_link_points_to_youth_policy(self):
        self.assertIn('href="https://wikischolar.bd/youth-policy"', self.client.get("/").content.decode())


class BanglaTests(WSTestCase):
    def test_labels_have_bangla(self):
        page = self.client.get("/").content.decode()
        for bn in ["শিক্ষার্থীর পুরো নাম", "অভিভাবকের নাম (আপনার নাম)", "জেলা", "থানা", "বিদ্যালয়ের নাম",
                   "রোল নম্বর", "শাখা (যদি থাকে)", "মোবাইল নম্বর", "যাচাই কোড পাঠান", "পরের ধাপ", "যুব সুরক্ষা নীতি",
                   "ষষ্ঠ শ্রেণি", "ছেলে", "মেয়ে", "উইকিস্কলারের কথা আপনি কোথা থেকে জানলেন?"]:
            self.assertIn(bn, page)
        self.assertIn('id="bnMessages"', page)

    def test_choice_lists_keep_their_own_bangla(self):
        """Relation "Other" and survey "Somewhere else" share the value "other" but not the Bangla."""
        page = self.client.get("/").content.decode()
        self.assertIn('value="other" required><span>Other <span class="bn-inline" lang="bn">অন্য</span>', page)
        self.assertIn("Somewhere else · অন্য কোথাও", page)

    def test_every_server_message_has_bangla(self):
        """Every message the form or the API can return must be in bangla.MESSAGES (looked up by the script)."""
        msgs = set(views.MESSAGES.values()) | {EMAIL_TAKEN_MESSAGE, forms.ROLL_OR_SID_ERROR, forms.REQUIRED["required"]}
        for form_cls in (forms.RegistrationForm,):
            for f in form_cls.base_fields.values():
                msgs |= {m for m in f.error_messages.values() if "%(" not in m}
        msgs |= {"Enter a valid Bangladeshi mobile number (for example 01712345678).",
                 "Write the class roll in numbers only (for example 12).", "Write the email address in English letters.",
                 "Write the student's relation to the guardian.", "Choose a thana in the selected district."}
        msgs -= {"spam", "Enter a valid UUID."}  # honeypot / not something a person can cause
        missing = sorted(m for m in msgs if m not in bangla.MESSAGES)
        self.assertEqual(missing, [])

    def test_script_messages_have_bangla(self):
        """Every English string register.js passes to bi()/biInline()/biText() is translated."""
        js = open("static/js/register.js", encoding="utf-8").read()
        used = set(re.findall(r'\b(?:bi|biInline|biText)\("([^"]+)"', js))
        used |= set(re.findall(r'^\s+\w+: "([^"]+)",$', js[js.index("const MSG"):js.index("const STEP_FIELDS")], re.M))
        missing = sorted(u for u in used if u not in bangla.MESSAGES)
        self.assertEqual(missing, [])

    def test_api_errors_carry_the_english_key(self):
        vid = self.verify_email()
        r = self.post_json("/api/registration/submit/", self.payload(vid, class_roll="", student_id_sid=""))
        self.assertIn(r.json()["errors"]["class_roll"][0], bangla.MESSAGES)


class HtmlEmailTests(WSTestCase):
    def html_of(self, message):
        return next(c for c, mime in message.alternatives if mime == "text/html")

    def test_otp_email_has_html_with_code_box_and_logo(self):
        self.verify_email()
        # verify_email cleared the outbox before sending, so the OTP is the only message
        msg = mail.outbox[0]
        code = re.search(r"\b(\d{6})\b", msg.body).group(1)
        html = self.html_of(msg)
        self.assertIn(code, html)
        self.assertIn("letter-spacing:8px", html)  # the code box
        self.assertIn("https://registration.wikischolar.bd/static/img/wikischolar-logo-en.png", html)
        self.assertIn("A Wikimedia Bangladesh programme", html)

    def test_confirmation_email_has_details_table(self):
        mail.outbox.clear()
        with self.captureOnCommitCallbacks(execute=True):
            s = self.register(section="C")
        msg = mail.outbox[-1]
        self.assertIn("Section: C", msg.body)
        html = self.html_of(msg)
        self.assertIn(s["wikischolar_id"], html)
        self.assertIn("<table", html)
        self.assertIn("TONGI GOVERNMENT HIGH SCHOOL", html)
        self.assertNotIn("{details}", html)

    def test_email_card_has_no_coloured_strip(self):
        self.assertNotIn("border-top:5px", html_email.render_html("Hello"))

    def test_html_escapes_and_links(self):
        out = html_email.text_to_html("Hi <b>you</b>\nsee https://wikischolar.bd/x and mail info@wikischolar.bd")
        self.assertIn("&lt;b&gt;you&lt;/b&gt;", out)
        self.assertIn('href="https://wikischolar.bd/x"', out)
        self.assertIn('href="mailto:info@wikischolar.bd"', out)

    @override_settings(WIKISCHOLAR=ws(PUBLIC_URL=""))
    def test_without_public_url_the_email_uses_a_text_wordmark(self):
        html = html_email.render_html("Hello")
        self.assertNotIn("<img", html)
        self.assertIn("Wiki<span", html)

    def test_bulk_messages_are_sent_with_html_too(self):
        from apps.notifications import services as notify
        log = notify.send_transactional_email("bulk", "x@example.com", "Hello", "Line one\n\nLine two")
        self.assertEqual(log.status, "sent")
        html = self.html_of(mail.outbox[-1])
        self.assertIn("Line one", html)
        self.assertIn("Line two", html)


class DashboardTests(WSTestCase):
    def test_nav_groups_related_tools(self):
        groups = nav_groups_for(self.super)
        labels = [g.label for g in groups]
        self.assertEqual(labels, ["", "Students", "Schools & places", "Messaging", "Administration"])
        messaging = next(g for g in groups if g.label == "Messaging")
        self.assertEqual([i.label for i in messaging.items], ["Messages", "System emails", "Email & SMS settings"])

    def test_single_tool_group_is_a_plain_link(self):
        viewer_groups = nav_groups_for(self.viewer)
        overview = next(g for g in viewer_groups if "dashboard:home" in g.url_names)
        self.assertEqual(overview.label, "")
        students = next(g for g in viewer_groups if "dashboard:students" in g.url_names)
        # a viewer can't open archived records, but has saved searches
        self.assertEqual([i.label for i in students.items], ["All students", "Saved searches"])

    def test_sidebar_renders_groups_open_on_current_page(self):
        self.client.force_login(self.super)
        page = self.client.get("/dashboard/schools/").content.decode()
        self.assertIn('class="nav-group" open', page)
        self.assertIn("<summary>Schools &amp; places</summary>", page)
        self.assertIn("img/wikischolar-logo-en.png", page)

    def test_student_detail_and_export_show_section_and_survey(self):
        s = self.register(section="A", heard_from="banner")
        self.client.force_login(self.admin)
        r = self.client.get(f"/dashboard/students/{s['wikischolar_id']}/")
        self.assertContains(r, "Heard about WikiScholar from")
        self.assertContains(r, "Banner")
        self.assertNotContains(r, "Date of birth")
        r = self.client.get("/dashboard/students/export.csv")
        content = b"".join(r.streaming_content).decode("utf-8-sig")
        header = content.splitlines()[0].split(",")
        self.assertIn("section", header)
        self.assertIn("heard_from", header)
        self.assertNotIn("date_of_birth", header)

    def test_overview_shows_survey_answers(self):
        self.register(heard_from="social_media")
        self.client.force_login(self.viewer)
        r = self.client.get("/dashboard/")
        self.assertContains(r, "How they heard about WikiScholar")
        self.assertContains(r, "1 answer.")

    def test_system_email_preview_is_html(self):
        self.client.force_login(self.super)
        r = self.client.get("/dashboard/settings/system-emails/")
        self.assertContains(r, 'class="email-preview"')
        self.assertContains(r, "srcdoc=")
