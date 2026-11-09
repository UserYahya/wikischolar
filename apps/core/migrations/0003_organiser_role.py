# New role "organiser" (statistics only). Only the field's choices change: no database change.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0002_integrity_triggers'),
    ]

    operations = [
        migrations.AlterField(
            model_name='admin',
            name='role',
            field=models.CharField(choices=[('super_admin', 'Super Admin'), ('admin', 'Admin'), ('viewer', 'Read-only Viewer'), ('organiser', 'Organiser (statistics only)')], default='viewer', max_length=20),
        ),
    ]
