from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render

from .capital_dashboard import build_dashboard


@staff_member_required
def capital_dashboard(request):
    dashboard = None
    error = None

    if request.method == "POST" and request.FILES.get("workbook"):
        try:
            dashboard = build_dashboard(workbook_file=request.FILES["workbook"])
        except Exception as exc:
            error = str(exc)
    else:
        try:
            dashboard = build_dashboard()
        except Exception as exc:
            error = str(exc)

    return render(
        request,
        "capital/dashboard.html",
        {
            "dashboard": dashboard,
            "error": error,
        },
    )
