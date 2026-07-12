from django.urls import path

from bank import views

urlpatterns = [
    path("health/", views.health),
    path("api/bank/upload", views.BankUploadView.as_view()),
    path("api/bank/export/credits", views.export_credits),
    path("api/bank/export/payments", views.export_payments),
]
