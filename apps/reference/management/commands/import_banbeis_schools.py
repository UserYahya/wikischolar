from django.core.management.base import BaseCommand, CommandError

from apps.reference import banbeis


class Command(BaseCommand):
    help = ("Load the government's school list (BANBEIS institution list .xlsx): EIIN, name, district, thana "
            "and the government data. Matches existing schools by EIIN, then by name in the same thana; "
            "adds the rest as verified. Safe to run again. Try --dry-run first.")

    def add_arguments(self, parser):
        parser.add_argument("xlsx_path")
        parser.add_argument("--dry-run", action="store_true", help="show what would change; save nothing")

    def handle(self, xlsx_path, dry_run, **opts):
        try:
            counts = banbeis.import_schools(xlsx_path, dry_run=dry_run, log=self.stdout.write)
        except (OSError, ValueError, KeyError) as exc:
            raise CommandError(f"Can't read {xlsx_path}: {exc}") from exc
        if counts["unresolved"] == counts["rows"]:
            raise CommandError("No rows could be imported.")
        self.stdout.write(self.style.SUCCESS(
            f"{counts['created']} created, {counts['matched_by_name']} matched by name, {counts['updated']} updated, "
            f"{counts['unchanged']} unchanged, {counts['unresolved']} skipped."
            + (" (dry run)" if dry_run else "")))
