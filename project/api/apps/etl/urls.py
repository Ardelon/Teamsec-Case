from django.urls import path
from apps.etl import views

urlpatterns = [
    path("", views.dashboard),
    path("jobs/", views.list_jobs),
    path("jobs/trigger/", views.trigger_job),
    path("jobs/<str:job_id>/", views.job_detail),
]
