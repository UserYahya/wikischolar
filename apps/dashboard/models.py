"""Dashboard data: saved advanced searches, shared by every admin who can see that list."""
from django.conf import settings
from django.db import models

from apps.core.models import SoftDeleteModel


class SavedSearch(SoftDeleteModel):
    class Entity(models.TextChoices):
        STUDENTS = "students", "Students"
        SCHOOLS = "schools", "Schools"

    # Who can see and run a saved search: anyone with the list's view permission.
    VIEW_PERM = {Entity.STUDENTS: "students.view", Entity.SCHOOLS: "schools.view"}

    entity = models.CharField(max_length=10, choices=Entity.choices)
    name = models.CharField(max_length=120)
    description = models.CharField(max_length=300, blank=True)
    query = models.JSONField()  # the advanced-search query (apps/dashboard/advanced.py)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="+")

    class Meta:
        db_table = "saved_searches"
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["entity", "name"], condition=models.Q(is_deleted=False),
                                               name="saved_search_entity_name_uniq")]

    def __str__(self):
        return self.name

    def can_change(self, user):
        """The admin who saved it, or a Super Admin, may update or delete it; everyone else can only run it."""
        return user.pk == self.created_by_id or user.has_perm_code("admins.manage")
