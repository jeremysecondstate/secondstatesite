from django.urls import path

from . import inventory_views as views

urlpatterns = [
    path("", views.inventory, name="inventory"),
    path("state/", views.state, name="inventory_state"),
    path("cases/", views.create_case, name="inventory_create"),
    path("trash/empty/", views.empty_trash, name="inventory_empty_trash"),
    path("<uuid:case_id>/", views.inventory, name="inventory_case"),
    path("<uuid:case_id>/trash/", views.delete_case, name="inventory_delete_case"),
    path("<uuid:case_id>/restore/", views.restore_case, name="inventory_restore_case"),
    path("<uuid:case_id>/messages/", views.add_message, name="inventory_message"),
    path("<uuid:case_id>/messages/<int:message_id>/trash/", views.delete_message, name="inventory_delete_message"),
    path("<uuid:case_id>/messages/<int:message_id>/restore/", views.restore_message, name="inventory_restore_message"),
    path("jobs/<uuid:job_id>/retry/", views.retry_job, name="inventory_retry"),
    path("api/claim/", views.claim, name="inventory_worker_claim"),
    path("api/lots/search/", views.lot_search, name="inventory_worker_search"),
    path("api/jobs/<uuid:job_id>/purchases/", views.purchases, name="inventory_worker_purchases"),
    path("api/jobs/<uuid:job_id>/status/", views.job_status, name="inventory_worker_status"),
    path("api/jobs/<uuid:job_id>/complete/", views.complete, name="inventory_worker_complete"),
    path("api/jobs/<uuid:job_id>/fail/", views.fail, name="inventory_worker_fail"),
]
