from django.urls import path

from . import api

app_name = "reference"
urlpatterns = [
    path("districts/", api.districts, name="districts"),
    path("districts/<int:district_id>/upazilas/", api.upazilas, name="upazilas"),
    path("schools/", api.schools, name="schools"),
]
