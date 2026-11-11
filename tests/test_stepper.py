"""The step numbers (1-4) above the registration form are buttons: analytics showed many dead clicks
on them, because only finished steps reacted. The behaviour itself lives in static/js/register.js
(goToStep) and was checked in a browser; these tests pin the pieces it relies on."""
from django.contrib.staticfiles import finders

from apps.registration.bangla import MESSAGES

from .base import WSTestCase


class StepperTests(WSTestCase):
    def test_page_has_the_blocked_move_note(self):
        page = self.client.get("/").content.decode()
        note = page[page.index('id="railNote"'):]
        note = note[:note.index("</p>")]
        self.assertIn('role="status" hidden', note)  # shown only when a move forward is stopped
        self.assertIn("Complete this step first, then you can move on.", note)
        self.assertIn("আগে এই ধাপটি পূরণ করুন, তারপর পরের ধাপে যেতে পারবেন।", note)
        self.assertEqual(page.count("data-step-tab="), 4)

    def test_every_step_number_is_a_button(self):
        js = open(finders.find("js/register.js"), encoding="utf-8").read()
        self.assertIn("function goToStep(target)", js)
        self.assertIn('const go = () => goToStep(Number(li.dataset.stepTab));', js)
        self.assertIn('li.setAttribute("role", "button");', js)
        self.assertNotIn('li.removeAttribute("role")', js)  # the current and later steps stay buttons
        for text in ("Go back to this step", "Go to this step", "You are on this step"):
            self.assertIn(f'"{text}"', js)
            self.assertIn(text, MESSAGES)
        css = open(finders.find("css/public.css"), encoding="utf-8").read()
        self.assertIn(".rail li { cursor: pointer;", css)
