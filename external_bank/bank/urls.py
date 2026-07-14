from django.urls import path

from bank import views

urlpatterns = [
    path("", views.portal),
    path("portal/", views.portal),
    path("portal/portfolios", views.portfolio_list_partial),
    path("health/", views.health),
    path("api/bank/upload", views.BankUploadView.as_view()),
    path("api/bank/export/credits", views.export_credits),
    path("api/bank/export/payments", views.export_payments),
    path("api/bank/download/credits", views.download_credits),
    path("api/bank/download/payments", views.download_payments),
]
