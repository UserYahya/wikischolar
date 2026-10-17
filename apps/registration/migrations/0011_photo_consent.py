# Youth Safety Policy 4.5: optional guardian permission for photos at offline events. Existing students
# get photo_consent = False (not given), which the check constraint allows.
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('registration', '0010_exam_reminder_in_saved_email'),
    ]

    operations = [
        migrations.AddField(
            model_name='student',
            name='photo_consent',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='student',
            name='photo_consent_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddConstraint(
            model_name='student',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('photo_consent', True), ('photo_consent_at__isnull', False)), models.Q(('photo_consent', False), ('photo_consent_at__isnull', True)), _connector='OR'), name='student_photo_consent'),
        ),
    ]
