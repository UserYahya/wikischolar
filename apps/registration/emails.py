"""The registration module's system emails. Their wording can be changed by a Super Admin on
Dashboard -> System emails; the defaults below are used until then (and after "Reset to default")."""
from django.conf import settings

from apps.notifications import services as notify

OTP = "registration.otp"
CONFIRMATION = "registration.confirmation"

_STUDENT_PLACEHOLDERS = {
    "student_name": "student's full name",
    "wikischolar_id": "the new WikiScholar ID, e.g. WS-2027-000001",
    "details": "all registration details, one per line (name, date of birth, guardian, district, "
               "upazila, school, class, roll / student ID, phone, who filled in the form)",
    "date_of_birth": "date of birth (YYYY-MM-DD)",
    "gender": "gender",
    "guardian": "guardian's name and relation, e.g. Karim Uddin (Father)",
    "district": "district",
    "region": "region (may be empty)",
    "upazila": "upazila",
    "school": "school name",
    "current_class": "class, e.g. Class 8",
    "class_roll": "class roll (may be empty)",
    "student_id_sid": "school student ID (may be empty)",
    "phone": "mobile number",
    "email": "email address",
    "filled_by": "who filled in the form: The student / The student's guardian",
    "contact_email": "the programme's contact address (WS_CONTACT_EMAIL)",
}

_SAMPLE_SUMMARY = {
    "wikischolar_id": "WS-2027-000123", "student_name": "Rahim Uddin", "date_of_birth": "2012-03-14",
    "gender": "Male", "guardian": "Karim Uddin (Father)", "district": "Gazipur", "region": "Dhaka",
    "upazila": "Tongi", "school": "Tongi Government High School", "current_class": "Class 8",
    "class_roll": "12", "student_id_sid": "", "phone": "01712345678", "email": "rahim@gmail.com",
    "filled_by": "The student's guardian",
}


def details_block(s):
    """The registration summary as plain-text lines (s = registration.services.summary())."""
    district = s["district"] + (f" ({s['region']} region)" if s.get("region") else "")
    lines = [f"Name: {s['student_name']}", f"Date of birth: {s['date_of_birth']}", f"Guardian: {s['guardian']}",
             f"District: {district}", f"Upazila: {s['upazila']}", f"School: {s['school']}",
             f"Class: {s['current_class']}"]
    if s.get("class_roll"):
        lines.append(f"Class roll: {s['class_roll']}")
    if s.get("student_id_sid"):
        lines.append(f"Student ID: {s['student_id_sid']}")
    lines += [f"Phone: {s['phone']}", f"Form filled in by: {s['filled_by']}"]
    return "\n".join(lines)


def confirmation_values(s):
    """Placeholder values for the confirmation email, from registration.services.summary()."""
    keys = set(_STUDENT_PLACEHOLDERS) - {"details", "contact_email"}
    values = {k: s.get(k, "") for k in keys}
    values.update(details=details_block(s), contact_email=settings.WIKISCHOLAR["CONTACT_EMAIL"])
    return values


def register():
    notify.register_system_email(notify.SystemEmail(
        key=OTP,
        label="Email verification code (OTP)",
        description="Sent when someone clicks “Send verification code” on the registration form.",
        subject="Your WikiScholar verification code",
        body=("Your WikiScholar verification code is {code}\n\n"
              "It expires in {minutes} minutes. If you didn't request it, you can ignore this email.\n"),
        placeholders={"code": "the 6-digit verification code", "minutes": "how many minutes the code is valid"},
        required=("code",),
        sample={"code": "123456", "minutes": str(settings.WIKISCHOLAR["OTP_TTL_MINUTES"])},
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
    ))
