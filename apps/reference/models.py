"""
Reference Data module: regions, districts, upazilas, canonical schools, aliases.

District -> Region is a nullable, editable foreign key. Nothing in code knows
which district belongs to which region; the mapping is seeded from
data/reference_seed.json once and then managed from the dashboard.
"""
from django.conf import settings
from django.contrib.postgres.indexes import GinIndex
from django.db import models

from apps.core.models import SoftDeleteModel

from .normalize import normalize_school_name


class Region(SoftDeleteModel):
    code = models.SlugField(max_length=40, unique=True)
    name = models.CharField(max_length=64)
    name_bn = models.CharField(max_length=64, blank=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "regions"
        ordering = ["sort_order", "name"]

    def __str__(self):
        return self.name


class District(SoftDeleteModel):
    code = models.SlugField(max_length=40, unique=True)
    name = models.CharField(max_length=64)
    name_bn = models.CharField(max_length=64, blank=True)
    region = models.ForeignKey(Region, null=True, blank=True, on_delete=models.PROTECT, related_name="districts")

    class Meta:
        db_table = "districts"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Upazila(SoftDeleteModel):
    """An area inside a district: the form's "Upazila / Area". Most rows are upazilas (blank `group`).
    City corporations have no upazila, so their thanas are rows too, grouped by city corporation
    (`group` = "Dhaka North City Corporation", …), and so are cantonments (`group` = "Cantonment")
    and one "Other area" per district (`group` = "Other") for anyone who can't find their area.
    Students and schools point at any of them the same way."""
    CANTONMENT = "Cantonment"
    OTHER = "Other"
    # Headings for groups that aren't a city corporation: (English, Bangla)
    GROUP_LABELS = {"": ("Upazilas", "উপজেলা"), CANTONMENT: ("Cantonments", "সেনানিবাস"),
                    OTHER: ("Not in the list", "তালিকায় নেই")}

    district = models.ForeignKey(District, on_delete=models.PROTECT, related_name="upazilas")
    name = models.CharField(max_length=80)
    name_bn = models.CharField(max_length=80, blank=True)
    group = models.CharField(max_length=60, blank=True)     # blank = an upazila
    group_bn = models.CharField(max_length=60, blank=True)  # Bangla of `group`

    class Meta:
        db_table = "upazilas"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["district", "name"], name="upazila_district_name_uniq"),
            # Target for the composite FK students(upazila_id, district_id)
            models.UniqueConstraint(fields=["id", "district"], name="upazila_id_district_uniq"),
        ]

    def __str__(self):
        return self.name

    @property
    def group_label(self):
        return self.GROUP_LABELS.get(self.group, (self.group, self.group_bn))[0]

    @property
    def group_label_bn(self):
        return self.GROUP_LABELS.get(self.group, (self.group, self.group_bn))[1]

    @property
    def display_name(self):
        """The name with its city corporation, e.g. "Mohammadpur (Dhaka North City Corporation)"."""
        if self.group and self.group not in (self.CANTONMENT, self.OTHER):
            return f"{self.name} ({self.group})"
        return self.name

    @property
    def sort_key(self):
        """Order in lists: city-corporation thanas, cantonments, upazilas, then "Other area"."""
        rank = {"": 2, self.CANTONMENT: 1, self.OTHER: 3}.get(self.group, 0)
        return (rank, self.group.casefold(), self.name.casefold())


class School(SoftDeleteModel):
    class Status(models.TextChoices):
        VERIFIED = "verified", "Verified"
        PENDING = "pending", "Pending review"
        MERGED = "merged", "Merged"

    class Source(models.TextChoices):
        REGISTRATION = "registration", "Added during registration"
        ADMIN = "admin", "Added by admin"
        IMPORT = "import", "Bulk import"

    name = models.CharField(max_length=255)
    name_normalized = models.CharField(max_length=255, editable=False)
    district = models.ForeignKey(District, on_delete=models.PROTECT, related_name="schools")
    # Blank = area not known yet (e.g. imported from a list with districts only). Such a school belongs
    # to the whole district: it is suggested and duplicate-checked across all its areas.
    upazila = models.ForeignKey(Upazila, null=True, blank=True, on_delete=models.PROTECT, related_name="schools")
    verification_status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    source = models.CharField(max_length=14, choices=Source.choices, default=Source.REGISTRATION)
    merged_into = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="merged_from")
    verified_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "schools"
        ordering = ["name"]
        indexes = [
            models.Index(fields=["upazila", "verification_status"], name="school_upz_status_idx"),
            GinIndex(fields=["name_normalized"], name="school_name_trgm", opclasses=["gin_trgm_ops"]),  # pg_trgm
        ]
        constraints = [
            models.CheckConstraint(
                condition=(models.Q(verification_status="merged", merged_into__isnull=False)
                           | (~models.Q(verification_status="merged") & models.Q(merged_into__isnull=True))),
                name="school_merged_has_target",
            ),
        ]

    def save(self, *args, **kwargs):
        self.name = " ".join((self.name or "").split())
        self.name_normalized = normalize_school_name(self.name)
        if self.upazila_id and not self.district_id:
            self.district_id = self.upazila.district_id
        super().save(*args, **kwargs)

    @property
    def area_name(self):
        """The upazila / area name, or "" when it isn't known yet."""
        return self.upazila.name if self.upazila_id else ""

    @property
    def location_label(self):
        """Where the school is, for messages: its area, or its district when the area isn't known."""
        return self.area_name or f"{self.district.name} (area not known)"

    def canonical(self):
        school, hops = self, 0
        while school.merged_into_id and hops < 20:
            school, hops = school.merged_into, hops + 1
        return school

    def __str__(self):
        return self.name


class SchoolAlias(SoftDeleteModel):
    class Source(models.TextChoices):
        MERGE = "merge", "From a merged duplicate"
        ADMIN = "admin", "Added by admin"
        RENAME = "rename", "Previous name"

    school = models.ForeignKey(School, on_delete=models.PROTECT, related_name="aliases")
    alias_text = models.CharField(max_length=255)
    alias_normalized = models.CharField(max_length=255, editable=False)
    source = models.CharField(max_length=10, choices=Source.choices, default=Source.ADMIN)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+")

    class Meta:
        db_table = "school_aliases"
        indexes = [GinIndex(fields=["alias_normalized"], name="alias_text_trgm", opclasses=["gin_trgm_ops"])]
        constraints = [models.UniqueConstraint(fields=["school", "alias_normalized"], name="alias_school_text_uniq")]

    def save(self, *args, **kwargs):
        self.alias_normalized = normalize_school_name(self.alias_text)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.alias_text} → {self.school_id}"
