from django.conf import settings
from django.contrib import admin
from django.urls import include
from django.urls import path
# from django.conf.urls.static import static
from django.urls import re_path
from django.views.static import serve as serve_media

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("secondstateapp.urls")),
]

# Serve media via Django (OK for small traffic, not best-practice)
urlpatterns += [
    re_path(
        r"^media/(?P<path>.*)$",
        serve_media,
        {"document_root": settings.MEDIA_ROOT},
    ),
]
