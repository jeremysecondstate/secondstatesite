from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("about/", views.about, name="about"),
    path("contact/", views.contact, name="contact"),
    path("gallery/", views.gallery, name="gallery"),
    path("pieces-sold/<int:pk>/", views.sold_piece_detail, name="sold_piece_detail"),
    path("accounts/register/", views.register, name="register"),
    path("accounts/login/", views.login_view, name="login"),
    path("accounts/logout/", views.logout_view, name="logout"),
    path("account/", views.account_profile, name="account_profile"),
    path("u/<str:username>/", views.public_profile, name="public_profile"),
    path("schwab/callback", views.schwab_callback, name="schwab_callback"),
    path("schwab/callback/", views.schwab_callback, name="schwab_callback_slash"),
    # Artworks
    path("artworks/", views.artwork_list, name="artwork_list"),
    path("artworks/<int:pk>/", views.artwork_detail, name="artwork_detail"),
    path("artworks/upload_artwork/", views.upload_artwork, name="upload_artwork"),
    path("artworks/delete_artwork/", views.delete_artwork, name="delete_artwork"),
    path("healthz", views.healthz, name="healthz"),
    path("pieces-sold/delete/", views.delete_sold_piece, name="delete_sold_piece"),
]