from django.contrib import admin
from .models import Booking, SessionSlot, CommunityPost, PhotoAlbum, CommunityPhoto

@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ['name', 'topic', 'slot', 'status', 'is_sample']
    list_filter = ['status', 'topic', 'is_sample']
    search_fields = ['name', 'contact']
    readonly_fields = ['reference', 'created_at', 'completed_at']

@admin.register(SessionSlot)
class SessionSlotAdmin(admin.ModelAdmin):
    list_display = ['starts_at', 'venue', 'duration_minutes']

admin.site.site_header = 'TechNeighbor administration'
admin.site.site_title = 'TechNeighbor'


@admin.register(CommunityPost)
class CommunityPostAdmin(admin.ModelAdmin):
    list_display = ['title', 'kind', 'starts_at', 'published', 'going_count']
    list_filter = ['kind', 'published', 'is_sample']
    readonly_fields = ['going_count', 'created_at']


@admin.register(PhotoAlbum)
class PhotoAlbumAdmin(admin.ModelAdmin):
    list_display = ['title', 'slug', 'color']


@admin.register(CommunityPhoto)
class CommunityPhotoAdmin(admin.ModelAdmin):
    list_display = ['title', 'album', 'uploader_name', 'status', 'created_at']
    list_filter = ['status', 'album']
    readonly_fields = ['width', 'height', 'created_at', 'reviewed_at']

    def has_add_permission(self, request):
        return False
