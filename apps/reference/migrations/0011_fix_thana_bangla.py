# Bangla names that 0007 carried over from an old name which no longer fits the government's name
# (e.g. Dhaka "Mirpur" kept "মিরপুর মডেল" from "Mirpur Model"). Same list as BANGLA_FIXES in
# scripts/build_thana_seed.py. A name an admin has changed since is left alone.
from django.db import migrations

FIXES = [  # (district code, thana, old Bangla, new Bangla)
    ("dhaka", "Mirpur", "মিরপুর মডেল", "মিরপুর"),
    ("dhaka", "Paltan", "পল্টন মডেল", "পল্টন"),
    ("dhaka", "Ramna", "রমনা মডেল", "রমনা"),
    ("dhaka", "Uttara", "উত্তরা পূর্ব", "উত্তরা"),
    ("dhaka", "Mugda Para", "মুগদা", "মুগদাপাড়া"),
    ("chittagong", "Chittagong Port", "বন্দর", "চট্টগ্রাম বন্দর"),
    ("pirojpur", "Indurkani", "জিয়ানগর", "ইন্দুরকানী"),
    ("barisal", "Barisal Sadar (Kotwali)", "বরিশাল সদর", "বরিশাল সদর (কোতোয়ালি)"),
    ("comilla", "Comilla Adarsha Sadar", "কুমিল্লা সদর", "কুমিল্লা আদর্শ সদর"),
    ("comilla", "Comilla Sadar Dakshin", "সদর দক্ষিণ", "কুমিল্লা সদর দক্ষিণ"),
    ("pirojpur", "Nesarabad (Swarupkati)", "নেছারাবাদ", "নেছারাবাদ (স্বরূপকাঠি)"),
    ("rangamati", "Kawkhali (Betbunia)", "কাউখালী", "কাউখালী (বেতবুনিয়া)"),
]


def forwards(apps, schema_editor):
    Thana = apps.get_model("reference", "Thana")
    for code, name, old, new in FIXES:
        Thana.objects.filter(district__code=code, name=name, name_bn=old).update(name_bn=new)


def backwards(apps, schema_editor):
    Thana = apps.get_model("reference", "Thana")
    for code, name, old, new in FIXES:
        Thana.objects.filter(district__code=code, name=name, name_bn=new).update(name_bn=old)


class Migration(migrations.Migration):
    dependencies = [("reference", "0010_uppercase_school_names")]
    operations = [migrations.RunPython(forwards, backwards)]
