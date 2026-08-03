from django.urls import path

from . import (
    calendar_views,
    capital_dashboard_views,
    catalog_api_views,
    legal_views,
    upload_safe_views,
    views,
)

urlpatterns = [
    path("", views.home, name="home"),
    path("about/", views.about, name="about"),
    path("contact/", views.contact, name="contact"),
    path("sms/", legal_views.sms_program, name="sms_program"),
    path("privacy/", legal_views.privacy_policy, name="privacy_policy"),
    path("sms-terms/", legal_views.sms_terms, name="sms_terms"),
    path("gallery/", views.gallery, name="gallery"),
    path("accounts/register/", views.register, name="register"),
    path("accounts/login/", views.login_view, name="login"),
    path("accounts/logout/", views.logout_view, name="logout"),
    path("account/", views.account_profile, name="account_profile"),
    path("u/<str:username>/", views.public_profile, name="public_profile"),
    path("capital-dashboard/", capital_dashboard_views.capital_dashboard, name="capital_dashboard"),
    path("calendar/", calendar_views.auction_calendar, name="auction_calendar"),
    path("calendar/sync/", calendar_views.sync_auction_calendar, name="auction_calendar_sync"),
    path(
        "calendar/lots/<int:lot_id>/artprice-link/",
        calendar_views.update_auction_lot_artprice_link,
        name="auction_lot_artprice_link",
    ),
    path(
        "calendar/lots/<int:lot_id>/artprice-analysis/",
        calendar_views.auction_lot_artprice_analysis,
        name="auction_lot_artprice_analysis",
    ),
    path(
        "calendar/reminders/control/",
        calendar_views.manage_auction_reminders,
        name="auction_reminder_control",
    ),
    path(
        "calendar/reminders/send/",
        calendar_views.send_due_auction_reminders,
        name="auction_reminder_send",
    ),
    path("schwab/callback", views.schwab_callback, name="schwab_callback"),
    path("schwab/callback/", views.schwab_callback, name="schwab_callback_slash"),
    # Artworks
    path("artworks/", views.artwork_list, name="artwork_list"),
    path("artworks/manage_json/", catalog_api_views.artwork_manage_list, name="artwork_manage_list"),
    path("artworks/reorder_artworks/", catalog_api_views.reorder_artworks, name="reorder_artworks"),
    path("artworks/generate_description/", catalog_api_views.generate_catalog_description_from_payload, name="generate_catalog_description_from_payload"),
    path("artworks/<int:pk>/", views.artwork_detail, name="artwork_detail"),
    path("artworks/<int:pk>/edit/", views.artwork_edit, name="artwork_edit"),
    path("artworks/<int:pk>/generate_description/", views.generate_artwork_description, name="generate_artwork_description"),
    path("artworks/<int:pk>/update_artwork/", catalog_api_views.update_artwork, name="update_artwork"),
    path("artworks/upload_artwork/", upload_safe_views.upload_artwork, name="upload_artwork"),
    path("artworks/delete_artwork/", views.delete_artwork, name="delete_artwork"),
    path("healthz", views.healthz, name="healthz"),
]
