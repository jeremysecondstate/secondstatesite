from django.contrib import admin

from .models import (
    Artwork,
    ArtworkImage,
    AuctionMaxBidAnalysis,
    AuctionReminderControl,
    AuctionReminderDelivery,
    AuctionWatchLot,
    SoldPiece,
    UserProfile,
)


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


@admin.register(AuctionWatchLot)
class AuctionWatchLotAdmin(admin.ModelAdmin):
    list_display = ("artist_label", "title", "auction_house", "event_at", "source_status", "active")
    search_fields = ("artist", "artist_watchlist_name", "title", "auction_house", "sale_title", "artprice_url")
    list_filter = ("active", "source_status", "source", "auction_house")
    date_hierarchy = "event_at"
    readonly_fields = ("created_at", "synced_at")

    @admin.display(description="Artist")
    def artist_label(self, obj):
        return obj.artist_watchlist_name or obj.artist


@admin.register(AuctionMaxBidAnalysis)
class AuctionMaxBidAnalysisAdmin(admin.ModelAdmin):
    list_select_related = ("lot",)
    list_display = (
        "lot",
        "resale_method",
        "currency",
        "expected_resale_hammer",
        "sold_records_count",
        "updated_at",
    )
    list_filter = ("resale_method", "currency")
    search_fields = (
        "lot__artist",
        "lot__artist_watchlist_name",
        "lot__title",
        "lot__auction_house",
        "source_filename",
    )
    readonly_fields = (
        "lot",
        "source_filename",
        "currency",
        "resale_method",
        "manual_resale_value",
        "recent_count",
        "expected_resale_hammer",
        "net_resale_proceeds",
        "inbound_shipping",
        "target_profit",
        "seller_commission_pct",
        "outbound_shipping",
        "other_resale_costs",
        "premium_min",
        "premium_max",
        "sold_records_count",
        "comparables",
        "bid_rows",
        "created_by",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request):
        return False


@admin.register(AuctionReminderDelivery)
class AuctionReminderDeliveryAdmin(admin.ModelAdmin):
    list_display = ("target_date", "days_before", "recipient_display", "status", "twilio_status", "attempted_at")
    list_filter = ("status", "days_before")
    search_fields = ("recipient_display", "twilio_message_sid")
    readonly_fields = (
        "target_date",
        "days_before",
        "recipient_hash",
        "recipient_display",
        "twilio_message_sid",
        "twilio_status",
        "covered_sale_hashes",
        "error",
        "attempted_at",
        "sent_at",
        "created_at",
        "updated_at",
    )


@admin.register(AuctionReminderControl)
class AuctionReminderControlAdmin(admin.ModelAdmin):
    list_display = ("active", "started_at", "paused_at", "updated_by", "last_run_status", "last_run_at")
    readonly_fields = (
        "singleton_key",
        "active",
        "started_at",
        "paused_at",
        "updated_by",
        "last_run_at",
        "last_run_source",
        "last_run_status",
        "last_run_summary",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request):
        return not AuctionReminderControl.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
