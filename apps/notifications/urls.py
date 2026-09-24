from django.urls import path

from . import views

app_name = "notifications"
urlpatterns = [path("webhook/<str:channel>/", views.delivery_webhook, name="webhook")]
