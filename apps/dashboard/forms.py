from django import forms
from django.contrib.auth.password_validation import validate_password

from apps.core.models import Admin, Role
from apps.core.utils import english_text
from apps.notifications import services as notify
from apps.notifications.models import Channel, EmailSettings, SmsSettings
from apps.reference.models import Region, School
from apps.registration.forms import StudentCoreFields
from apps.registration.validators import normalize_phone, validate_phone


class StudentEditForm(StudentCoreFields):
    school = forms.ModelChoiceField(queryset=School.objects.filter(merged_into__isnull=True))
    reason = forms.CharField(max_length=255, required=False, label="Reason for change")

    def clean(self):
        data = super().clean()
        # A student may attend a school in another thana of their district (as on the form)
        school, district = data.get("school"), data.get("district")
        if school and district and school.district_id != district.pk:
            self.add_error("school", "This school is not in the selected district.")
        return data


GOVERNMENT_FIELDS = ["eiin", "division", "institute_type", "education_level", "management", "mpo", "institute_for",
                     "geographical_position", "area_status", "post_office", "email"]


class SchoolDetailsForm(forms.ModelForm):
    """A school's government data (EIIN, management, MPO, …), as on the BANBEIS list."""

    class Meta:
        model = School
        fields = GOVERNMENT_FIELDS

    def clean_eiin(self):
        eiin = self.cleaned_data["eiin"].strip()
        if eiin and not (len(eiin) == 6 and eiin.isdigit()):
            raise forms.ValidationError("An EIIN is 6 digits.")
        if eiin and School.all_objects.filter(eiin=eiin).exclude(pk=self.instance.pk).exists():
            other = School.all_objects.filter(eiin=eiin).first()
            raise forms.ValidationError(f"EIIN {eiin} already belongs to {other.name}.")
        return eiin

    def clean_division(self):
        return english_text(self.cleaned_data["division"]) if self.cleaned_data["division"] else ""

    def clean_post_office(self):
        return english_text(self.cleaned_data["post_office"]) if self.cleaned_data["post_office"] else ""


class ComposeForm(forms.Form):
    name = forms.CharField(
        max_length=120, label="Batch name",
        error_messages={"required": "Give this batch a name, so you can find it and see who received it later."},
        widget=forms.TextInput(attrs={"placeholder": "e.g. Exam invite - Dhaka - Oct 2026"}))
    channel = forms.ChoiceField(choices=Channel.choices, widget=forms.RadioSelect)
    subject = forms.CharField(max_length=200, required=False)
    body = forms.CharField(widget=forms.Textarea(attrs={"rows": 8}), max_length=5000)
    opted_in_only = forms.BooleanField(required=False, initial=True)
    confirm_count = forms.IntegerField(widget=forms.HiddenInput)

    def clean_name(self):
        return english_text(self.cleaned_data["name"])  # names are searched later: one script only

    def clean(self):
        data = super().clean()
        if data.get("channel") == Channel.EMAIL and not data.get("subject"):
            self.add_error("subject", "Email needs a subject.")
        return data


class AdminCreateForm(forms.Form):
    full_name = forms.CharField(max_length=150)
    email = forms.EmailField()
    role = forms.ChoiceField(choices=Role.choices)
    password = forms.CharField(widget=forms.PasswordInput, help_text="Temporary password, at least 12 characters.")

    def clean_email(self):
        email = self.cleaned_data["email"].lower()
        if Admin.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An admin with this email already exists.")
        return email

    def clean_password(self):
        validate_password(self.cleaned_data["password"])
        return self.cleaned_data["password"]


class RegionForm(forms.ModelForm):
    class Meta:
        model = Region
        fields = ["name", "name_bn", "code", "sort_order"]

    def clean_name(self):
        return english_text(self.cleaned_data["name"])


class EmailSettingsForm(forms.ModelForm):
    password = forms.CharField(
        widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "new-password"}), required=False,
        label="Password / SMTP key / API key", help_text="Stored encrypted. Leave blank to keep the saved one.")

    class Meta:
        model = EmailSettings
        fields = ["provider", "username", "from_email", "from_name", "reply_to", "host", "port", "security",
                  "is_active"]
        labels = {"username": "Username / SMTP login", "from_email": "From address", "from_name": "From name",
                  "reply_to": "Reply-to address",
                  "host": "SMTP host", "port": "Port", "is_active": "Use these settings for all outgoing email"}

    def clean(self):
        data = super().clean()
        provider = data.get("provider")
        if provider == EmailSettings.Provider.CONSOLE:
            return data
        if not data.get("username") and provider != EmailSettings.Provider.BREVO_API:
            self.add_error("username", "Required for this provider.")
        if not data.get("password") and not self.instance.has_password:
            self.add_error("password", "Required for this provider.")
        elif not data.get("password") and not self.instance._state.adding and provider != self.instance.provider:
            # the saved secret belongs to the old provider (e.g. a Gmail app password is not a Brevo API key)
            self.add_error("password", "You changed the provider: enter the password / key for the new one.")
        if provider == EmailSettings.Provider.BREVO_API and (data.get("password") or "").startswith("xsmtpsib-"):
            self.add_error("password", "That is a Brevo SMTP key. Use an API key (starts with xkeysib-) "
                                       "from SMTP & API → API keys, or choose “Brevo (SMTP relay)”.")
        if provider == EmailSettings.Provider.SMTP and not data.get("host"):
            self.add_error("host", "Enter the SMTP server host name.")
        return data

    def save(self, commit=True):
        obj = super().save(commit=False)
        if self.cleaned_data.get("password"):
            obj.set_password(self.cleaned_data["password"])
        if commit:
            obj.save()
        return obj


class TestEmailForm(forms.Form):
    to = forms.EmailField(label="Send a test email to")


class SmsSettingsForm(forms.ModelForm):
    api_key = forms.CharField(
        widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "new-password"}), required=False,
        label="API key", help_text="Stored encrypted. Leave blank to keep the saved one.")

    class Meta:
        model = SmsSettings
        fields = ["provider", "username", "sender_name", "api_url", "is_active"]
        labels = {"username": "API username (MiM SMS login email)", "sender_name": "Sender ID",
                  "api_url": "API base URL", "is_active": "Use these settings for all outgoing SMS"}

    def clean_username(self):
        return self.cleaned_data["username"].strip()

    def clean_sender_name(self):
        return self.cleaned_data["sender_name"].strip()

    def clean(self):
        data = super().clean()
        if data.get("provider") == SmsSettings.Provider.CONSOLE:
            return data
        if not data.get("username"):
            self.add_error("username", "Required: the email you use to sign in at sms.mimsms.com.")
        if not data.get("api_key") and not self.instance.has_api_key:
            self.add_error("api_key", "Required: copy it from sms.mimsms.com → Utility → Developer.")
        if not data.get("sender_name"):
            self.add_error("sender_name", "Required: an approved Sender ID from sms.mimsms.com → Utility → Sender ID.")
        return data

    def save(self, commit=True):
        obj = super().save(commit=False)
        if self.cleaned_data.get("api_key"):
            obj.set_api_key(self.cleaned_data["api_key"].strip())
        if commit:
            obj.save()
        return obj


class TestSmsForm(forms.Form):
    phone = forms.CharField(max_length=20, label="Send a test SMS to")

    def clean_phone(self):
        phone = normalize_phone(self.cleaned_data["phone"])
        validate_phone(phone)
        return phone


class SystemEmailForm(forms.Form):
    """Wording of one registered system email (see notifications.services.register_system_email)."""
    subject = forms.CharField(max_length=200)
    body = forms.CharField(widget=forms.Textarea(attrs={"rows": 12}), max_length=10000, strip=False)

    def __init__(self, *args, email, **kwargs):
        super().__init__(*args, prefix=email.key, **kwargs)
        self.email = email

    def clean_subject(self):
        subject = " ".join(self.cleaned_data["subject"].split())  # one line
        if not subject:
            raise forms.ValidationError("Enter a subject.")
        return subject

    def clean_body(self):
        body = self.cleaned_data["body"].replace("\r\n", "\n")
        if not body.strip():
            raise forms.ValidationError("Enter the email text.")
        return body

    def clean(self):
        data = super().clean()
        if "subject" in data and "body" in data:
            for problem in notify.template_problems(self.email, data["subject"], data["body"]):
                self.add_error("body", problem)
        return data
