from django.urls import path
from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("about/", views.about, name="about"),
    path("contact/", views.contact, name="contact"),
    path("gallery/", views.gallery, name="gallery"),
    path("pieces-sold/", views.pieces_sold, name="pieces_sold"),
    # Artworks
    path("artworks/", views.artwork_list, name="artwork_list"),
    path("artworks/<int:pk>/", views.artwork_detail, name="artwork_detail"),
    path("artworks/upload_artwork/", views.upload_artwork, name="upload_artwork"),
    path("artworks/delete_artwork/", views.delete_artwork, name="delete_artwork"),

    path("healthz", views.healthz, name="healthz"),

    path("sales/upload_sales_sheet/", views.upload_sales_sheet, name="upload_sales_sheet"),
    path("sales/list/", views.sales_list, name="sales_list"),
    path("sales/add/", views.sales_add, name="sales_add"),
    path("sales/delete/", views.sales_delete, name="sales_delete"),

]
