from django.db import models


class Gender(models.TextChoices):
    MALE = "male", "Male"
    FEMALE = "female", "Female"
    UNDISCLOSED = "undisclosed", "Prefer not to say"


class FilledBy(models.TextChoices):
    """Who filled in the registration form (the guardian declares it with a checkbox)."""
    STUDENT = "student", "The student"
    GUARDIAN = "guardian", "The student's guardian"


class GuardianRelation(models.TextChoices):
    FATHER = "father", "Father"
    MOTHER = "mother", "Mother"
    OTHER = "other", "Other"


# WikiScholar is for classes 6-10 only (also enforced by a DB check constraint).
CLASS_CHOICES = [(str(n), f"Class {n}") for n in range(6, 11)]
CLASS_VALUES = [v for v, _ in CLASS_CHOICES]


class HeardFrom(models.TextChoices):
    """Survey on the registration form: how the family heard about WikiScholar."""
    SOCIAL_MEDIA = "social_media", "Social media"
    ONLINE_AD = "online_ad", "Google or YouTube ad"
    WIKIPEDIA_NOTICE = "wikipedia_notice", "Notice on Wikipedia"
    SCHOOL = "school", "Teacher or school announcement"
    BANNER = "banner", "Banner / leaflet etc."
    VOLUNTEERS = "volunteers", "Wikipedia volunteers came to our school"
    OTHER = "other", "Somewhere else"
