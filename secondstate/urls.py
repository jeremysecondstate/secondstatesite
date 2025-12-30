from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("secondstateapp.urls")),
]

# Serve media via Django (OK for small traffic, not best-practice)
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)