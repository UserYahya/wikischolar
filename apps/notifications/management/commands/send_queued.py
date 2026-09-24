from django.core.management.base import BaseCommand

from apps.notifications.models import EmailBatch, SmsBatch
from apps.notifications.services import dispatch_batch


class Command(BaseCommand):
    help = ("Send every queued bulk message (run from cron every minute, or a worker loop). Safe to run while "
            "the dashboard is sending too: each message is claimed once.")

    def handle(self, **opts):
        n = 0
        for model in (EmailBatch, SmsBatch):
            for batch in model.objects.filter(logs__status="queued").distinct():
                left = dispatch_batch(batch)
                n += 1
                self.stdout.write(f"{batch.batch_code}: {left} still queued")
        self.stdout.write(self.style.SUCCESS(f"Dispatched {n} batch(es)."))
