from django.urls import path

from apps.etl import views

urlpatterns = [
    path("sync", views.sync_data),
    path("sync/active", views.active_sync),
    path("sync/status/<str:job_id>", views.sync_status),
    path("data", views.data_snapshot),
    path("profiling", views.profiling_metrics),
]
