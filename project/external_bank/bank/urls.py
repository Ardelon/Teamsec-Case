from django.urls import path
from bank import views

urlpatterns = [
    path("health/", views.health),
    path("api/v1/loans/<str:tenant_id>/", views.loan_feed),
]
