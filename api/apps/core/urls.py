from django.urls import include, path

from apps.core import views

urlpatterns = [
    path("health/", views.health),
    path("auth/login", views.login),
    path("auth/logout", views.logout),
    path("auth/session", views.session_info),
    path("", include("apps.etl.urls")),
]
