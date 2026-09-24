"""
Notification module. Batches are append-only records of what was sent;
notification_logs is the junction between a batch and each recipient
(by student + wikischolar_id) and carries per-recipient delivery status.
"""
from django.conf import settings
from django.db import models
from django.utils import timezone


class Channel(models.TextChoices):
    EMAIL = "email", "Email"
    SMS = "sms", "SMS"


class BatchBase(models.Model):
    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        SENDING = "sending", "Sending"
        COMPLETED = "completed", "Completed"

    batch_code = models.CharField(max_length=24, unique=True)
    # Admin-chosen label ("Exam invite - Dhaka - Oct 2026") to find and track a send later.
    name = models.CharField(max_length=120, blank=True, db_index=True)
    body = models.TextField()
    filter_snapshot = models.JSONField(default=dict, blank=True)
    opted_in_only = models.BooleanField(default=False)
    recipient_count = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.QUEUED)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        abstract = True
        ordering = ["-created_at"]


class EmailBatch(BatchBase):
    subject = models.CharField(max_length=200)
    channel = Channel.EMAIL

    class Meta(BatchBase.Meta):
        db_table = "email_batches"

    def __str__(self):
        return self.batch_code

    @property
    def label(self):
        return self.name or self.batch_code


class SmsBatch(BatchBase):
    channel = Channel.SMS

    class Meta(BatchBase.Meta):
        db_table = "sms_batches"

    def __str__(self):
        return self.batch_code

    @property
    def label(self):
        return self.name or self.batch_code


class NotificationLog(models.Model):
    class Kind(models.TextChoices):
        OTP = "otp", "Email verification code"
        CONFIRMATION = "confirmation", "Registration confirmation"
        BULK = "bulk", "Bulk message"

    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        SENT = "sent", "Sent"
        DELIVERED = "delivered", "Delivered"
        FAILED = "failed", "Failed"
        BOUNCED = "bounced", "Bounced"

    # Definitely did not reach the recipient (rejected when sending, or bounced afterwards).
    NOT_DELIVERED = (Status.FAILED, Status.BOUNCED)

    channel = models.CharField(max_length=5, choices=Channel.choices)
    kind = models.CharField(max_length=12, choices=Kind.choices)
    email_batch = models.ForeignKey(EmailBatch, null=True, blank=True, on_delete=models.PROTECT, related_name="logs")
    sms_batch = models.ForeignKey(SmsBatch, null=True, blank=True, on_delete=models.PROTECT, related_name="logs")
    student = models.ForeignKey("registration.Student", null=True, blank=True, on_delete=models.PROTECT,
                                related_name="notifications")
    wikischolar_id = models.CharField(max_length=20, blank=True, db_index=True)
    destination = models.CharField(max_length=254)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.QUEUED, db_index=True)
    provider = models.CharField(max_length=40, blank=True)
    provider_message_id = models.CharField(max_length=200, blank=True, db_index=True)
    error = models.TextField(blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    resend_of = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="resends")
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    status_updated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "notification_logs"
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=(models.Q(email_batch__isnull=True) | models.Q(sms_batch__isnull=True)),
                name="notif_single_batch"),
            models.CheckConstraint(
                condition=(models.Q(channel="email", sms_batch__isnull=True)
                           | models.Q(channel="sms", email_batch__isnull=True)),
                name="notif_batch_matches_channel"),
        ]


class EmailSettings(models.Model):
    """Outgoing-email credentials, managed by Super Admins on the dashboard (one row, pk=1).
    When active, every email (OTP, confirmation, bulk) uses it instead of the EMAIL_* env settings."""

    class Provider(models.TextChoices):
        BREVO = "brevo", "Brevo (SMTP relay)"
        BREVO_API = "brevo_api", "Brevo (HTTPS API: use when the host blocks SMTP)"
        GMAIL = "gmail", "Google Mail / Workspace"
        SMTP = "smtp", "Other SMTP server"
        CONSOLE = "console", "Console (development: print, don't send)"

    class Security(models.TextChoices):
        STARTTLS = "starttls", "STARTTLS (usually port 587)"
        SSL = "ssl", "SSL/TLS (usually port 465)"
        NONE = "none", "None"

    # Fixed connection details for the named providers; "smtp" uses the stored ones.
    PRESETS = {
        Provider.BREVO: {"host": "smtp-relay.brevo.com", "port": 587, "security": Security.STARTTLS},
        Provider.GMAIL: {"host": "smtp.gmail.com", "port": 587, "security": Security.STARTTLS},
    }

    provider = models.CharField(max_length=10, choices=Provider.choices, default=Provider.BREVO)
    host = models.CharField(max_length=255, blank=True)
    port = models.PositiveIntegerField(default=587)
    security = models.CharField(max_length=10, choices=Security.choices, default=Security.STARTTLS)
    username = models.CharField(max_length=255, blank=True)
    password_encrypted = models.TextField(blank=True)
    from_email = models.EmailField()
    from_name = models.CharField(max_length=100, default="WikiScholar")
    reply_to = models.EmailField(blank=True, default="")  # where replies go; blank = the From address
    is_active = models.BooleanField(default=False)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="+")
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "email_settings"

    @classmethod
    def active(cls):
        return cls.objects.filter(pk=1, is_active=True).first()

    @property
    def has_password(self):
        return bool(self.password_encrypted)

    def set_password(self, raw):
        from apps.core.crypto import encrypt
        self.password_encrypted = encrypt(raw)

    def connection_params(self):
        """Effective host / port / security (named providers use their preset)."""
        preset = self.PRESETS.get(self.provider, {})
        return (preset.get("host", self.host), preset.get("port", self.port), preset.get("security", self.security))

    @property
    def from_header(self):
        from email.utils import formataddr
        return formataddr((self.from_name, self.from_email)) if self.from_name else self.from_email

    def connection(self):
        from django.core.mail import get_connection

        from apps.core.crypto import decrypt
        if self.provider == self.Provider.CONSOLE:
            return get_connection("django.core.mail.backends.console.EmailBackend")
        if self.provider == self.Provider.BREVO_API:
            return get_connection("apps.notifications.backends.BrevoApiBackend",
                                  api_key=decrypt(self.password_encrypted), timeout=20)
        host, port, security = self.connection_params()
        return get_connection(
            "django.core.mail.backends.smtp.EmailBackend", host=host, port=port,
            username=self.username, password=decrypt(self.password_encrypted),
            use_tls=security == self.Security.STARTTLS, use_ssl=security == self.Security.SSL, timeout=20)

    def audit_view(self):
        """What the audit log may record: never the password."""
        host, port, security = self.connection_params()
        return {"provider": self.provider, "host": host, "port": port, "security": security,
                "username": self.username, "from_email": self.from_email, "from_name": self.from_name,
                "reply_to": self.reply_to, "is_active": self.is_active, "password_set": self.has_password}


class SmsSettings(models.Model):
    """SMS gateway credentials, managed by Super Admins on Dashboard -> Email & SMS settings (one row, pk=1).
    When active, every SMS uses it instead of the NOTIFY_SMS_PROVIDER env setting."""

    class Provider(models.TextChoices):
        MIMSMS = "mimsms", "MiM SMS"
        CONSOLE = "console", "Console (development: log, don't send)"

    provider = models.CharField(max_length=10, choices=Provider.choices, default=Provider.MIMSMS)
    api_url = models.URLField(default="https://api.mimsms.com/api")
    username = models.CharField(max_length=254, blank=True)  # MiM SMS panel login email
    api_key_encrypted = models.TextField(blank=True)
    sender_name = models.CharField(max_length=20, blank=True)  # approved Sender ID (masking name or number)
    is_active = models.BooleanField(default=False)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="+")
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "sms_settings"

    @classmethod
    def active(cls):
        return cls.objects.filter(pk=1, is_active=True).first()

    @property
    def has_api_key(self):
        return bool(self.api_key_encrypted)

    def set_api_key(self, raw):
        from apps.core.crypto import encrypt
        self.api_key_encrypted = encrypt(raw)

    @property
    def api_key(self):
        from apps.core.crypto import decrypt
        return decrypt(self.api_key_encrypted)

    def provider_instance(self):
        from .providers.sms import ConsoleSmsProvider, MimSmsProvider
        if self.provider == self.Provider.CONSOLE:
            return ConsoleSmsProvider()
        return MimSmsProvider(api_url=self.api_url, username=self.username, api_key=self.api_key,
                              sender_name=self.sender_name)

    def audit_view(self):
        """What the audit log may record: never the API key."""
        return {"provider": self.provider, "api_url": self.api_url, "username": self.username,
                "sender_name": self.sender_name, "is_active": self.is_active, "api_key_set": self.has_api_key}


class EmailTemplate(models.Model):
    """A Super Admin's wording for a system email (e.g. the OTP or registration confirmation).
    The modules that send these emails register their keys, placeholders and default text
    (notifications.services.register_system_email). One row per key; while is_customized is False
    the default is used, so "Reset to default" never deletes anything."""
    key = models.CharField(max_length=60, unique=True)
    subject = models.CharField(max_length=200)
    body = models.TextField()
    is_customized = models.BooleanField(default=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="+")
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "email_templates"

    def __str__(self):
        return self.key
