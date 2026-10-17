# The confirmation email now asks students to check their email regularly (exam announcements are sent
# by email). A Super Admin may have customised its wording on Dashboard -> System emails before; the
# saved text is what gets sent, so add the same line there too: before the "Questions?" / contact line,
# or at the end. Texts that already mention exam announcements are left alone.
from django.db import migrations

LINE = ("Please check this email address regularly: exam announcements and other WikiScholar updates "
        "will be sent here.")


def add_line(body):
    if "exam announcement" in body.lower():
        return body
    lines = body.rstrip("\n").split("\n")
    at = next((i for i, line in enumerate(lines) if "Questions?" in line or "{contact_email}" in line), None)
    if at is None:
        lines += ["", LINE]
    else:
        lines.insert(at, LINE)
    return "\n".join(lines) + "\n"


def forwards(apps, schema_editor):
    EmailTemplate = apps.get_model("notifications", "EmailTemplate")
    for row in EmailTemplate.objects.filter(key="registration.confirmation", is_customized=True):
        body = add_line(row.body)
        if body != row.body:
            row.body = body
            row.save(update_fields=["body"])


class Migration(migrations.Migration):
    dependencies = [
        ("registration", "0009_rename_upazila_to_thana"),
        ("notifications", "0008_email_templates"),
    ]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
