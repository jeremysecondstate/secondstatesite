from django.contrib import admin

from .models import Artwork, ArtworkImage, SoldPiece, UserProfile


class ArtworkImageInline(admin.TabularInline):
    model = ArtworkImage
    extra = 1


@admin.register(Artwork)
class ArtworkAdmin(admin.ModelAdmin):
    list_display = ("display_order", "title", "artist", "price", "is_available")
    list_display_links = ("title",)
    ordering = ("display_order", "id")
    search_fields = ("title", "artist", "catalog_number")
    list_filter = ("is_available", "artist")
    inlines = [ArtworkImageInline]


@admin.register(SoldPiece)
class SoldPieceAdmin(admin.ModelAdmin):
    list_display = ("title", "artist", "date", "sale_location")
    search_fields = ("title", "artist", "sale_location")
    list_filter = ("sale_location",)


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "display_name", "updated_at")
    search_fields = ("user__username", "display_name", "user__email")
