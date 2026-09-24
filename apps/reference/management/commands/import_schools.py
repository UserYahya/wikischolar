import csv

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.reference.models import School, Upazila
from apps.reference.normalize import normalize_school_name


class Command(BaseCommand):
    help = "Import a canonical school list. CSV columns: district,upazila,name (English names as in the DB)."

    def add_arguments(self, parser):
        parser.add_argument("csv_path")
        parser.add_argument("--status", default="verified", choices=["verified", "pending"])

    @transaction.atomic
    def handle(self, csv_path, status, **opts):
        created = skipped = missing = 0
        with open(csv_path, newline="", encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                upz = Upazila.objects.filter(district__name__iexact=row["district"].strip(),
                                             name__iexact=row["upazila"].strip()).first()
                if not upz:
                    missing += 1
                    self.stderr.write(f"Unknown location: {row['district']} / {row['upazila']}")
                    continue
                if School.objects.filter(upazila=upz, name_normalized=normalize_school_name(row["name"])).exists():
                    skipped += 1
                    continue
                School.objects.create(name=row["name"], upazila=upz, district_id=upz.district_id,
                                      verification_status=status, source=School.Source.IMPORT)
                created += 1
        if missing and not created:
            raise CommandError("No rows imported.")
        self.stdout.write(self.style.SUCCESS(f"{created} created, {skipped} already existed, {missing} unknown locations."))
