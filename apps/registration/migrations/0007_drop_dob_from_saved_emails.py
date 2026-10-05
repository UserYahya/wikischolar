# Date of birth is no longer collected, so {date_of_birth} is no longer a placeholder. A Super Admin may have
# used it in a customised confirmation email; drop those lines so the email doesn't show "{date_of_birth}".
from django.db import migrations


def drop_dob_lines(apps, schema_editor):
    EmailTemplate = apps.get_model("notifications", "EmailTemplate")
    for row in EmailTemplate.objects.filter(key="registration.confirmation"):
        fields = []
        for name in ("subject", "body"):
            text = getattr(row, name)
            if "{date_of_birth}" in text:
                kept = [line for line in text.split("\n") if "{date_of_birth}" not in line]
                setattr(row, name, "\n".join(kept))
                fields.append(name)
        if fields:
            row.save(update_fields=fields)


class Migration(migrations.Migration):
    dependencies = [
        ("registration", "0006_section_survey_drop_dob"),
        ("notifications", "0008_email_templates"),
    ]
    operations = [migrations.RunPython(drop_dob_lines, migrations.RunPython.noop)]
