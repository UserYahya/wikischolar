from django.core.management.base import BaseCommand, CommandError

from apps.reference import importer


class Command(BaseCommand):
    help = ("Import a school list. CSV columns: district, thana (optional: blank or left out when not "
            "known), name (names as in the DB; the dashboard's Schools → Import offers a template). Same checks "
            "as the dashboard import; similar names are added.")

    def add_arguments(self, parser):
        parser.add_argument("csv_path")
        parser.add_argument("--status", default="verified", choices=["verified", "pending"])

    def handle(self, csv_path, status, **opts):
        try:
            with open(csv_path, "rb") as fh:
                rows = importer.read_rows(fh.read())
        except (OSError, importer.ImportFileError) as exc:
            raise CommandError(str(exc)) from exc
        planned = importer.plan(rows)
        similar = {r["line"] for r in planned if r["result"] == importer.SIMILAR}
        created, planned = importer.apply(rows, status=status, add_similar=similar)
        for r in planned:
            if r["result"] in (importer.ERROR, importer.REPEATED):
                self.stderr.write(f"Row {r['line']}: {r['message']}")
        c = importer.summary(planned)
        if not created and c[importer.ERROR]:
            raise CommandError("No rows imported.")
        self.stdout.write(self.style.SUCCESS(
            f"{len(created)} created, {c[importer.EXISTS]} already existed, {c[importer.REPEATED]} repeated, "
            f"{c[importer.ERROR]} with errors."))
