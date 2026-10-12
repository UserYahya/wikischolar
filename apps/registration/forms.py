from django import forms

from apps.reference.models import District, Thana

from .choices import CLASS_CHOICES, Gender, GuardianRelation, HeardFrom
from .validators import english_text, normalize_phone, roll_number, validate_phone

ROLL_OR_SID_ERROR = "Fill in either the class roll or the student ID."
REQUIRED = {"required": "This field is required."}


class StudentCoreFields(forms.Form):
    """Fields and cross-field rules shared by public registration and admin edits."""
    student_name = forms.CharField(max_length=150, error_messages=REQUIRED)
    gender = forms.ChoiceField(choices=Gender.choices, error_messages=REQUIRED)
    guardian_name = forms.CharField(max_length=150, error_messages=REQUIRED)
    guardian_relation = forms.ChoiceField(choices=GuardianRelation.choices, error_messages=REQUIRED)
    guardian_relation_other = forms.CharField(max_length=60, required=False)
    district = forms.ModelChoiceField(queryset=District.objects.all(), error_messages=REQUIRED)
    thana = forms.ModelChoiceField(queryset=Thana.objects.all(), error_messages=REQUIRED)
    current_class = forms.ChoiceField(choices=CLASS_CHOICES, error_messages=REQUIRED)
    class_roll = forms.CharField(max_length=20, required=False)
    student_id_sid = forms.CharField(max_length=40, required=False)
    section = forms.CharField(max_length=20, required=False)
    phone = forms.CharField(max_length=20, error_messages=REQUIRED)
    email = forms.EmailField(error_messages={**REQUIRED, "invalid": "Enter a valid email address."})
    updates_opt_in = forms.BooleanField(required=False)

    def clean_student_name(self):
        return english_text(self.cleaned_data["student_name"])

    def clean_guardian_name(self):
        return english_text(self.cleaned_data["guardian_name"])

    def clean_guardian_relation_other(self):
        return english_text(self.cleaned_data["guardian_relation_other"])

    def clean_class_roll(self):
        return roll_number(self.cleaned_data["class_roll"])

    def clean_section(self):
        return english_text(self.cleaned_data["section"])

    def clean_student_id_sid(self):
        return english_text(self.cleaned_data["student_id_sid"])

    def clean_phone(self):
        phone = normalize_phone(self.cleaned_data["phone"])
        validate_phone(phone)
        return phone

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if not email.isascii():
            raise forms.ValidationError("Write the email address in English letters.")
        return email

    def clean(self):
        data = super().clean()
        roll, sid = data.get("class_roll") or "", data.get("student_id_sid") or ""
        other = data.get("guardian_relation_other") or ""
        if data.get("guardian_relation") == GuardianRelation.OTHER:
            if not other and "guardian_relation_other" not in self.errors:
                self.add_error("guardian_relation_other", "Write the student's relation to the guardian.")
        else:
            other = ""  # the text box only applies to "Other"
        data["guardian_relation_other"] = other
        if not roll and not sid and "class_roll" not in self.errors and "student_id_sid" not in self.errors:
            self.add_error("class_roll", ROLL_OR_SID_ERROR)
            self.add_error("student_id_sid", ROLL_OR_SID_ERROR)
        district, thana = data.get("district"), data.get("thana")
        if district and thana and thana.district_id != district.pk:
            self.add_error("thana", "Choose a thana in the selected district.")
        return data


class RegistrationForm(StudentCoreFields):
    school_id = forms.IntegerField(required=False)
    school_name = forms.CharField(max_length=255, error_messages=REQUIRED)
    verification_id = forms.UUIDField(error_messages={"required": "Verify your email address first."})
    heard_from = forms.ChoiceField(choices=HeardFrom.choices, error_messages={
        "required": "Choose how you heard about WikiScholar.", "invalid_choice": "Choose how you heard about WikiScholar."})
    policy_consent = forms.BooleanField(error_messages={
        "required": "Agree to the Youth Safety Policy to complete registration."})
    # Youth Safety Policy: the guardian fills in the form and declares it.
    guardian_declaration = forms.BooleanField(error_messages={
        "required": "Tick the guardian declaration: the form must be filled in by the student's guardian."})
    website = forms.CharField(required=False)  # honeypot; real users never see it

    def clean_school_name(self):
        return english_text(self.cleaned_data["school_name"])

    def clean_email(self):
        # Also checked here, not only on "Send verification code": two tabs could verify the same address.
        from .services import EMAIL_TAKEN_MESSAGE, email_registered
        email = super().clean_email()
        if email_registered(email):
            raise forms.ValidationError(EMAIL_TAKEN_MESSAGE)
        return email

    def clean_website(self):
        if self.cleaned_data.get("website"):
            raise forms.ValidationError("spam")
        return ""
