from django.contrib import admin
from django.urls import include, path

from apps.etl import views as etl_views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("apps.core.urls")),
    path("", etl_views.login_page),
    path("dashboard/", etl_views.dashboard),
    path("login/", etl_views.login_page),
    path("etl/", etl_views.dashboard),
]
