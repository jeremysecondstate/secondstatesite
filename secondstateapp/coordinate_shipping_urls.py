from django.urls import path

from . import coordinate_shipping_views as views

urlpatterns = [
    path("<uuid:case_id>/plan/", views.update_plan, name="coordinate_plan"),
    path("<uuid:case_id>/quotes/", views.add_quote, name="coordinate_quote_add"),
    path("<uuid:case_id>/quotes/<uuid:quote_id>/", views.update_quote, name="coordinate_quote_update"),
    path("<uuid:case_id>/quotes/<uuid:quote_id>/accept/", views.accept_quote, name="coordinate_quote_accept"),
    path("<uuid:case_id>/quotes/<uuid:quote_id>/review/", views.resolve_quote, name="coordinate_quote_resolve"),
    path("<uuid:case_id>/drafts/", views.add_draft, name="coordinate_draft_add"),
    path("<uuid:case_id>/drafts/<uuid:draft_id>/", views.update_draft, name="coordinate_draft_update"),
    path("<uuid:case_id>/drafts/<uuid:draft_id>/review/", views.review_draft, name="coordinate_draft_review"),
]
