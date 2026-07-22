from pathlib import Path

from django.conf import settings
from django.contrib import admin
from django.http import FileResponse, Http404
from django.urls import include
from django.urls import path
# from django.conf.urls.static import static
from django.urls import re_path
from django.views.static import serve as serve_media


def twilio_domain_verification(request):
    file_path = (
        Path(settings.BASE_DIR)
        / "379470fc303616c42ca87909cc24f2d0.html"
    )

    if not file_path.exists():
        raise Http404("Verification file not found")

    return FileResponse(
        file_path.open("rb"),
        content_type="text/html",
    )

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("secondstateapp.urls")),
    path(
        "379470fc303616c42ca87909cc24f2d0.html",
        twilio_domain_verification,
        name="twilio-domain-verification",
    ),
]

# Serve media via Django (OK for small traffic, not best-practice)
urlpatterns += [
    re_path(
        r"^media/(?P<path>.*)$",
        serve_media,
        {"document_root": settings.MEDIA_ROOT},
    ),
]
