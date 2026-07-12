from django.urls import include, path

from apps.core import views
from apps.etl import views as etl_views

urlpatterns = [
    path("health/", views.health),
    path("auth/login", views.login),
    path("", include("apps.etl.urls")),
]
