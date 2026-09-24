import getpass

from django.core.management.base import BaseCommand, CommandError

from apps.core.models import Admin, Role


class Command(BaseCommand):
    help = "Create the first Super Admin (later admins are created from the dashboard)."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True)
        parser.add_argument("--name", required=True)
        parser.add_argument("--password", help="Omit to be prompted (recommended).")

    def handle(self, email, name, password=None, **opts):
        if Admin.objects.filter(email__iexact=email).exists():
            raise CommandError("An admin with this email already exists.")
        password = password or getpass.getpass("Password: ")
        Admin.objects.create_user(email=email, password=password, full_name=name, role=Role.SUPER_ADMIN)
        self.stdout.write(self.style.SUCCESS(f"Super Admin {email} created."))
