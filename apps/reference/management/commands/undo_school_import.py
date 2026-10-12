from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.core.models import AuditLog
from apps.reference import importer


class Command(BaseCommand):
    help = ("Undo a school import (dashboard Schools → Import or import_schools): its schools are removed, "
            "as with a school page's Remove school, and can be restored from Schools → Removed. --list shows "
            "recent imports; pass an import's id, with --dry-run first. Schools students are linked to are kept.")

    def add_arguments(self, parser):
        parser.add_argument("import_id", nargs="?", type=int, help="the id shown by --list")
        parser.add_argument("--list", action="store_true", help="show the 20 most recent imports")
        parser.add_argument("--dry-run", action="store_true", help="show what would be removed; change nothing")
        parser.add_argument("--yes", action="store_true", help="don't ask for confirmation")

    def handle(self, import_id, dry_run, yes, **opts):
        imports = AuditLog.objects.filter(action="school.imported")
        if opts["list"] or import_id is None:
            undone = set(AuditLog.objects.filter(action="school.import_undone").values_list("entity_id", flat=True))
            for e in imports.order_by("-created_at")[:20]:
                self.stdout.write(f"{e.pk:>6}  {_when(e)}  {e.actor_label or '-':<30}  {e.meta.get('created', 0):>5} "
                                  f"schools ({e.meta.get('status', '')})" + ("  [undone]" if str(e.pk) in undone else ""))
            if import_id is None:
                self.stdout.write("Pass one of these ids to undo that import (try --dry-run first).")
            return
        entry = imports.filter(pk=import_id).first()
        if not entry:
            raise CommandError(f"No school import with id {import_id}. Use --list to see them.")

        removed, kept, gone = importer.undo(entry, dry_run=True)
        self.stdout.write(f"Import {entry.pk} on {_when(entry)} by {entry.actor_label or '-'}: "
                          f"{len(entry.meta.get('ids') or [])} schools.")
        verb = "Would remove" if dry_run else "Will remove"
        for s in sorted(removed, key=lambda s: (s.upazila.name, s.name)):
            self.stdout.write(f"  {verb}: #{s.pk} {s.name} ({s.upazila.name})")
        for s, reason in kept.items():
            self.stdout.write(self.style.WARNING(f"  Keep: #{s.pk} {s.name} — {reason}"))
        if dry_run or not removed:
            self.stdout.write(f"{len(removed)} to remove, {len(kept)} kept, {len(gone)} already removed. "
                              "Nothing changed.")
            return
        if not yes and input(f"Remove {len(removed)} schools? Type REMOVE to confirm: ").strip() != "REMOVE":
            raise CommandError("Cancelled. Nothing changed.")
        removed, kept, gone = importer.undo(entry)  # checked again in case anything changed meanwhile
        self.stdout.write(self.style.SUCCESS(f"{len(removed)} removed, {len(kept)} kept, {len(gone)} already removed. "
                                             "They can be restored from Dashboard → Schools → Removed."))


def _when(entry):
    return timezone.localtime(entry.created_at).strftime("%d/%m/%Y %H:%M")
