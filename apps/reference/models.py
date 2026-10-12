"""
Reference Data module: regions, districts, thanas, canonical schools, aliases.

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


class Thana(SoftDeleteModel):
    """A thana inside a district: the form's "Thana". The list is the government's (BANBEIS
    e-survey 2024) plus newer upazilas; most rows have a blank `group`. Cantonments are rows too
    (`group` = "Cantonment"), and so is one "Other thana (not listed)" per district (`group` =
    "Other") for anyone who can't find theirs. Any other `group` is shown as a heading the thana is
    listed under (none in the current list). Students and schools point at any of them the same way."""
    CANTONMENT = "Cantonment"
    OTHER = "Other"
    # Headings for the groups: (English, Bangla)
    GROUP_LABELS = {"": ("Thanas", "থানা"), CANTONMENT: ("Cantonments", "সেনানিবাস"),
                    OTHER: ("Not in the list", "তালিকায় নেই")}

    district = models.ForeignKey(District, on_delete=models.PROTECT, related_name="thanas")
    name = models.CharField(max_length=80)
    name_bn = models.CharField(max_length=80, blank=True)
    group = models.CharField(max_length=60, blank=True)     # blank = a thana
    group_bn = models.CharField(max_length=60, blank=True)  # Bangla of `group`

    class Meta:
        db_table = "thanas"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["district", "name"], name="thana_district_name_uniq"),
            # Target for the composite FK students(thana_id, district_id)
            models.UniqueConstraint(fields=["id", "district"], name="thana_id_district_uniq"),
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
        """The name with its group heading, e.g. "Mohammadpur (Dhaka North City Corporation)"; cantonments
        and "Other" are shown by name alone."""
        if self.group and self.group not in (self.CANTONMENT, self.OTHER):
            return f"{self.name} ({self.group})"
        return self.name

    @property
    def sort_key(self):
        """Order in lists: grouped thanas (if any), cantonments, thanas, then "Other thana"."""
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
        GOVERNMENT = "government", "BANBEIS list"

    # Government data (BANBEIS institution list, `manage.py import_banbeis_schools`); blank when unknown.
    class InstituteType(models.TextChoices):
        SCHOOL = "school", "School"
        SCHOOL_AND_COLLEGE = "school_and_college", "School & college"
        COLLEGE = "college", "College"

    class EducationLevel(models.TextChoices):
        SECONDARY = "secondary", "Secondary"
        JUNIOR_SECONDARY = "junior_secondary", "Junior secondary"
        PRIMARY_TO_EIGHT = "primary_to_eight", "Govt. primary (pre to eight)"
        HIGHER_SECONDARY = "higher_secondary", "Higher secondary"
        DEGREE_PASS = "degree_pass", "Degree (pass)"
        DEGREE_HONOURS = "degree_honours", "Degree (honours)"
        MASTERS = "masters", "Masters"

    class Management(models.TextChoices):
        GOVERNMENT = "government", "Government"
        NON_GOVERNMENT = "non_government", "Non-government"
        LOCAL_GOVERNMENT = "local_government", "Local government"
        AUTONOMOUS = "autonomous", "Autonomous"
        CANTONMENT_BOARD = "cantonment_board", "Cantonment board"
        CHRISTIAN_MISSIONARY = "christian_missionary", "Christian missionary"
        NGO = "ngo", "NGO"
        OTHER = "other", "Other"

    class Mpo(models.TextChoices):
        YES = "yes", "Yes"
        NO = "no", "No"
        NOT_APPLICABLE = "not_applicable", "Not applicable"

    class InstituteFor(models.TextChoices):
        CO_EDUCATION = "co_education", "Co-education"
        SEPARATE_SHIFT = "co_education_separate_shift", "Co-education (separate shifts)"
        GIRLS = "girls", "Girls"
        BOYS = "boys", "Boys"

    class GeographicalPosition(models.TextChoices):
        PLAIN_LAND = "plain_land", "Plain land"
        RIVER_SIDE = "river_side", "River side"
        HILLY_AREA = "hilly_area", "Hilly area"
        COASTAL_INSIDE = "coastal_inside", "Coastal area (inside embankment)"
        COASTAL_OUTSIDE = "coastal_outside", "Coastal area (outside embankment)"
        HAOR_INSIDE = "haor_inside", "Haor/Bil (inside embankment)"
        HAOR_OUTSIDE = "haor_outside", "Haor/Bil (outside embankment)"
        TEA_GARDEN = "tea_garden", "Tea garden"
        CHAR = "char", "Char"
        BORDER_AREA = "border_area", "Border area"
        INDUSTRIAL_AREA = "industrial_area", "Industrial area"
        ISLAND = "island", "Island (dwip)"
        SALINE_AREA = "saline_area", "Saline area"
        WATER_LOGGED = "water_logged", "Water logged"
        OTHER = "other", "Other"

    class AreaStatus(models.TextChoices):
        RURAL = "rural", "Rural"
        CITY_CORPORATION = "city_corporation", "City corporation"
        DISTRICT_SADAR_POURA = "district_sadar_poura", "District sadar paurashava"
        UPAZILA_SADAR_POURA = "upazila_sadar_poura", "Upazila sadar paurashava"
        UPAZILA_SADAR_NOT_POURA = "upazila_sadar_not_poura", "Upazila sadar (not paurashava)"
        OTHER_POURA = "other_poura", "Other paurashava areas"

    name = models.CharField(max_length=255)
    name_normalized = models.CharField(max_length=255, editable=False)
    district = models.ForeignKey(District, on_delete=models.PROTECT, related_name="schools")
    # Blank = thana not known yet (e.g. imported from a list with districts only). Such a school belongs
    # to the whole district: it is suggested and duplicate-checked across all its thanas.
    thana = models.ForeignKey(Thana, null=True, blank=True, on_delete=models.PROTECT, related_name="schools")
    verification_status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING, db_index=True)
    source = models.CharField(max_length=14, choices=Source.choices, default=Source.REGISTRATION)
    merged_into = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="merged_from")
    verified_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    verified_at = models.DateTimeField(null=True, blank=True)
    # Government data (blank when unknown). EIIN: the 6-digit Educational Institute Identification Number.
    eiin = models.CharField("EIIN", max_length=6, blank=True)
    division = models.CharField(max_length=40, blank=True)
    institute_type = models.CharField(max_length=20, choices=InstituteType.choices, blank=True)
    education_level = models.CharField(max_length=20, choices=EducationLevel.choices, blank=True, db_index=True)
    management = models.CharField(max_length=24, choices=Management.choices, blank=True, db_index=True)
    mpo = models.CharField("MPO", max_length=16, choices=Mpo.choices, blank=True)
    institute_for = models.CharField(max_length=30, choices=InstituteFor.choices, blank=True)
    geographical_position = models.CharField(max_length=20, choices=GeographicalPosition.choices, blank=True)
    area_status = models.CharField(max_length=26, choices=AreaStatus.choices, blank=True, db_index=True)
    post_office = models.CharField(max_length=80, blank=True)
    email = models.EmailField(blank=True)

    class Meta:
        db_table = "schools"
        ordering = ["name"]
        indexes = [
            models.Index(fields=["thana", "verification_status"], name="school_thana_status_idx"),
            GinIndex(fields=["name_normalized"], name="school_name_trgm", opclasses=["gin_trgm_ops"]),  # pg_trgm
        ]
        constraints = [
            models.CheckConstraint(
                condition=(models.Q(verification_status="merged", merged_into__isnull=False)
                           | (~models.Q(verification_status="merged") & models.Q(merged_into__isnull=True))),
                name="school_merged_has_target",
            ),
            models.UniqueConstraint(fields=["eiin"], condition=~models.Q(eiin=""), name="school_eiin_uniq"),
            models.CheckConstraint(condition=models.Q(eiin="") | models.Q(eiin__regex=r"^[0-9]{6}$"),
                                   name="school_eiin_six_digits"),
        ]

    def save(self, *args, **kwargs):
        self.name = " ".join((self.name or "").split()).upper()  # school names are always in capitals
        self.name_normalized = normalize_school_name(self.name)
        if self.thana_id and not self.district_id:
            self.district_id = self.thana.district_id
        super().save(*args, **kwargs)

    @property
    def area_name(self):
        """The thana name, or "" when it isn't known yet."""
        return self.thana.name if self.thana_id else ""

    @property
    def location_label(self):
        """Where the school is, for messages: its thana, or its district when the thana isn't known."""
        return self.area_name or f"{self.district.name} (thana not known)"

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
        self.alias_text = " ".join((self.alias_text or "").split()).upper()
        self.alias_normalized = normalize_school_name(self.alias_text)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.alias_text} → {self.school_id}"
