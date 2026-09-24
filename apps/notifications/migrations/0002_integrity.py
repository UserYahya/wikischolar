from django.db import migrations

from apps.core.sql import forbid_delete, run


class Migration(migrations.Migration):
    dependencies = [("notifications", "0001_initial"), ("core", "0002_integrity_triggers")]
    operations = run(migrations, [forbid_delete("email_batches"), forbid_delete("sms_batches"),
                                  forbid_delete("notification_logs")])
