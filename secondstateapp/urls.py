from django.urls import path

from . import capital_dashboard_views, catalog_api_views, upload_safe_views, views

urlpatterns = [
    path("", views.home, name="home"),
    path("about/", views.about, name="about"),
    path("contact/", views.contact, name="contact"),
    path("gallery/", views.gallery, name="gallery"),
    path("accounts/register/", views.register, name="register"),
    path("accounts/login/", views.login_view, name="login"),
    path("accounts/logout/", views.logout_view, name="logout"),
    path("account/", views.account_profile, name="account_profile"),
    path("u/<str:username>/", views.public_profile, name="public_profile"),
    path("capital-dashboard/", capital_dashboard_views.capital_dashboard, name="capital_dashboard"),
    path("schwab/callback", views.schwab_callback, name="schwab_callback"),
    path("schwab/callback/", views.schwab_callback, name="schwab_callback_slash"),
    # Artworks
    path("artworks/", views.artwork_list, name="artwork_list"),
    path("artworks/manage_json/", catalog_api_views.artwork_manage_list, name="artwork_manage_list"),
    path("artworks/reorder_artworks/", catalog_api_views.reorder_artworks, name="reorder_artworks"),
    path("artworks/generate_description/", catalog_api_views.generate_catalog_description_from_payload, name="generate_catalog_description_from_payload"),
    path("artworks/search_upcoming_print_auctions/", catalog_api_views.search_upcoming_print_auctions, name="search_upcoming_print_auctions"),
    path(
        "artworks/search_upcoming_print_auctions/<uuid:job_id>/status/",
        catalog_api_views.search_upcoming_print_auctions_status,
        name="search_upcoming_print_auctions_status",
    ),
    path("artworks/<int:pk>/", views.artwork_detail, name="artwork_detail"),
    path("artworks/<int:pk>/edit/", views.artwork_edit, name="artwork_edit"),
    path("artworks/<int:pk>/generate_description/", views.generate_artwork_description, name="generate_artwork_description"),
    path("artworks/<int:pk>/update_artwork/", catalog_api_views.update_artwork, name="update_artwork"),
    path("artworks/upload_artwork/", upload_safe_views.upload_artwork, name="upload_artwork"),
    path("artworks/delete_artwork/", views.delete_artwork, name="delete_artwork"),
    path("healthz", views.healthz, name="healthz"),
]
