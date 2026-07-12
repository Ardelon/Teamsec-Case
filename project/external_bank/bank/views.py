import json
from django.http import JsonResponse

FAKE_LOANS = {
    "tenant_alpha": [
        {"loan_id": "LA-001", "type": "mortgage", "principal": "250000.00", "rate": "3.50"},
        {"loan_id": "LA-002", "type": "auto", "principal": "18000.00", "rate": "5.20"},
    ],
    "tenant_beta": [
        {"loan_id": "LB-101", "type": "personal", "principal": "12000.00", "rate": "7.10"},
    ],
}


def health(request):
    return JsonResponse({"status": "ok", "service": "external_bank_sim"})


def loan_feed(request, tenant_id):
    loans = FAKE_LOANS.get(tenant_id, [])
    return JsonResponse({"tenant_id": tenant_id, "loans": loans})
