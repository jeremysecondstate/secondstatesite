from django.urls import include, path

from . import coordinate_views as views
from . import coordinate_intake as intake

urlpatterns = [
    path("", include("secondstateapp.coordinate_shipping_urls")),
    path("", views.coordinate, name="coordinate"),
    path("state/", views.state, name="coordinate_state"),
    path("cases/", views.create_case, name="coordinate_create"),
    path("<uuid:case_id>/", views.coordinate, name="coordinate_case"),
    path("<uuid:case_id>/messages/", views.add_message, name="coordinate_message"),
    path("<uuid:case_id>/documents/", intake.add_document, name="coordinate_intake_add"),
    path("<uuid:case_id>/documents/<uuid:document_id>/", intake.download_document, name="coordinate_intake_download"),
    path("<uuid:case_id>/trash/", views.delete_case, name="coordinate_delete_case"),
    path("<uuid:case_id>/restore/", views.restore_case, name="coordinate_restore_case"),
    path("<uuid:case_id>/messages/<int:message_id>/delete/", views.delete_message, name="coordinate_delete_message"),
    path("<uuid:case_id>/messages/<int:message_id>/restore/", views.restore_message, name="coordinate_restore_message"),
    path("api/claim/", views.claim, name="coordinate_worker_claim"),
    path("api/jobs/<uuid:job_id>/complete/", views.complete, name="coordinate_worker_complete"),
    path("api/jobs/<uuid:job_id>/fail/", views.fail, name="coordinate_worker_fail"),
]
