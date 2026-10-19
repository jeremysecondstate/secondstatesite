from django.urls import path

from . import coordinate_mail_views as views
from . import coordinate_mail_sync as sync

urlpatterns = [
    path("mail/readiness/", views.readiness, name="coordinate_mail_readiness"),
    path("mail/connection/", views.check_connection, name="coordinate_mail_check_connection"),
    path("<uuid:case_id>/drafts/<uuid:draft_id>/send/", views.send_draft, name="coordinate_mail_send"),
    path("api/mail/sync/", sync.sync_manifest, name="coordinate_mail_sync_manifest"),
    path("api/mail/import/", sync.import_mail, name="coordinate_mail_sync_import"),
]
