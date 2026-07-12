from django.urls import path
from apps.core import views

urlpatterns = [
    path("health/", views.health),
    path("auth/token/", views.issue_token),
]
