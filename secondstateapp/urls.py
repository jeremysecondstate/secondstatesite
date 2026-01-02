from django.urls import path
from . import views
urlpatterns = [
    path("", views.home, name="home"),
    path("about/", views.about, name="about"),
    path("contact/", views.contact, name="contact"),
    path("gallery/", views.gallery, name="gallery"),
    # path("pieces-sold/", views.pieces_sold, name="pieces_sold"),
    path("pieces-sold/", views.sold_list, name="pieces_sold"),
    path("pieces-sold/<int:pk>/", views.sold_piece_detail, name="sold_piece_detail"),
    # Artworks
    path("artworks/", views.artwork_list, name="artwork_list"),
    path("artworks/<int:pk>/", views.artwork_detail, name="artwork_detail"),
    path("artworks/upload_artwork/", views.upload_artwork, name="upload_artwork"),
    path("artworks/delete_artwork/", views.delete_artwork, name="delete_artwork"),
    path("healthz", views.healthz, name="healthz"),
    path("pieces-sold/upload/", views.upload_sold_piece, name="upload_sold_piece"),
    path("pieces-sold/delete/", views.delete_sold_piece, name="delete_sold_piece"),
]