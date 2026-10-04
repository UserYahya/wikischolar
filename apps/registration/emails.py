"""The registration module's system emails. Their wording can be changed by a Super Admin on
Dashboard -> System emails; the defaults below are used until then (and after "Reset to default")."""
from django.conf import settings

from apps.notifications import html_email
from apps.notifications import services as notify

OTP = "registration.otp"
CONFIRMATION = "registration.confirmation"

_STUDENT_PLACEHOLDERS = {
    "student_name": "student's full name",
    "wikischolar_id": "the new WikiScholar ID, e.g. WS-2027-000001",
    "details": "all registration details, one per line (name, guardian, district, upazila, school, class, "
               "section, roll / student ID, phone, who filled in the form); a table in the HTML email",
    "gender": "gender",
    "guardian": "guardian's name and relation, e.g. Karim Uddin (Father)",
    "district": "district",
    "region": "region (may be empty)",
    "upazila": "upazila or area (a thana shows its city corporation)",
    "school": "school name",
    "current_class": "class, e.g. Class 8",
    "class_roll": "class roll (may be empty)",
    "student_id_sid": "school student ID (may be empty)",
    "section": "class section (may be empty)",
    "phone": "mobile number",
    "email": "email address",
    "filled_by": "who filled in the form: The student / The student's guardian",
    "contact_email": "the programme's contact address (WS_CONTACT_EMAIL)",
}

_SAMPLE_SUMMARY = {
    "wikischolar_id": "WS-2027-000123", "student_name": "Rahim Uddin",
    "gender": "Male", "guardian": "Karim Uddin (Father)", "district": "Gazipur", "region": "Dhaka",
    "upazila": "Tongi", "school": "Tongi Government High School", "current_class": "Class 8",
    "class_roll": "12", "student_id_sid": "", "section": "B", "phone": "01712345678", "email": "rahim@gmail.com",
    "filled_by": "The student's guardian",
}


def details_rows(s):
    """The registration summary as (label, value) pairs (s = registration.services.summary())."""
    district = s["district"] + (f" ({s['region']} region)" if s.get("region") else "")
    rows = [("Name", s["student_name"]), ("Guardian", s["guardian"]), ("District", district),
            ("Upazila / Area", s["upazila"]), ("School", s["school"]), ("Class", s["current_class"])]
    for label, key in (("Section", "section"), ("Class roll", "class_roll"), ("Student ID", "student_id_sid")):
        if s.get(key):
            rows.append((label, s[key]))
    return rows + [("Phone", s["phone"]), ("Form filled in by", s["filled_by"])]


def details_block(s):
    """The registration summary as plain-text lines (the table in the HTML email)."""
    return "\n".join(f"{label}: {value}" for label, value in details_rows(s))


def confirmation_values(s):
    """Placeholder values for the confirmation email, from registration.services.summary()."""
    keys = set(_STUDENT_PLACEHOLDERS) - {"details", "contact_email"}
    values = {k: s.get(k, "") for k in keys}
    values.update(details=details_block(s), contact_email=settings.WIKISCHOLAR["CONTACT_EMAIL"])
    values["_rows"] = details_rows(s)  # for the HTML table; not a placeholder
    return values


def _otp_html(values):
    return {"code": html_email.code_box(values.get("code", ""))}


def _confirmation_html(values):
    return {"wikischolar_id": html_email.highlight(values.get("wikischolar_id", "")),
            "details": html_email.details_table(values.get("_rows", []))}


def register():
    notify.register_system_email(notify.SystemEmail(
        key=OTP,
        label="Email verification code (OTP)",
        description="Sent when someone clicks “Send verification code” on the registration form.",
        subject="Your WikiScholar verification code",
        body=("Your WikiScholar verification code is:\n\n"
              "{code}\n\n"
              "It expires in {minutes} minutes. If you didn't request it, you can ignore this email.\n"),
        placeholders={"code": "the 6-digit verification code", "minutes": "how many minutes the code is valid"},
        required=("code",),
        sample={"code": "123456", "minutes": str(settings.WIKISCHOLAR["OTP_TTL_MINUTES"])},
        html_values=_otp_html,
    ))
    notify.register_system_email(notify.SystemEmail(
        key=CONFIRMATION,
        label="Registration confirmation",
        description="Sent right after a student registers successfully.",
        subject="WikiScholar registration complete: {wikischolar_id}",
        body=("Dear {student_name},\n\n"
              "Your WikiScholar registration is complete.\n\n"
              "WikiScholar ID: {wikischolar_id}\n\n"
              "{details}\n\n"
              "Please use this ID in all future communication with WikiScholar.\n"
              "Questions? Contact us: {contact_email}\n"),
        placeholders=_STUDENT_PLACEHOLDERS,
        required=("wikischolar_id",),
        sample=confirmation_values(_SAMPLE_SUMMARY),
        html_values=_confirmation_html,
    ))
