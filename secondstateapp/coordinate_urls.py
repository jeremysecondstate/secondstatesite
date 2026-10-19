from django.urls import path

from . import coordinate_views as views

urlpatterns = [
    path("", views.coordinate, name="coordinate"),
    path("state/", views.state, name="coordinate_state"),
    path("cases/", views.create_case, name="coordinate_create"),
    path("<uuid:case_id>/", views.coordinate, name="coordinate_case"),
    path("<uuid:case_id>/messages/", views.add_message, name="coordinate_message"),
    path("api/claim/", views.claim, name="coordinate_worker_claim"),
    path("api/jobs/<uuid:job_id>/complete/", views.complete, name="coordinate_worker_complete"),
    path("api/jobs/<uuid:job_id>/fail/", views.fail, name="coordinate_worker_fail"),
]
