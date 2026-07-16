from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render

from .capital_dashboard import save_uploaded_workbook, saved_workbook_info
from .capital_dashboard_supreme import build_dashboard


@staff_member_required
def capital_dashboard(request):
    dashboard = None
    error = None
    saved_message = None

    if request.method == "POST" and request.FILES.get("workbook"):
        try:
            saved_path = save_uploaded_workbook(request.FILES["workbook"])
            saved_message = "Saved SUPREME workbook to private storage and refreshed the dashboard."
            dashboard = build_dashboard(workbook_path=saved_path)
        except Exception as exc:
            error = str(exc)
    else:
        try:
            dashboard = build_dashboard()
        except Exception as exc:
            error = str(exc)

    return render(
        request,
        "capital/dashboard_supreme.html",
        {
            "dashboard": dashboard,
            "error": error,
            "saved_message": saved_message,
            "saved_workbook": saved_workbook_info(),
        },
    )
