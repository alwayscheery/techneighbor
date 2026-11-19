from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path
from booking import views
from booking.hosted import health
from booking import credential_views, reward_views
from booking import community_views, neighbor_views
urlpatterns = [
    path('community/fund/', reward_views.community_fund, name='community_fund'),
    path('coordinator/booking/<uuid:reference>/reward/', reward_views.approve, name='approve_reward'),
    path('rewards/<uuid:public_id>/', reward_views.receipt, name='reward_receipt'),
    path('coordinator/rewards/<uuid:public_id>/pay/', reward_views.pay, name='pay_reward'),
    path('healthz/', health, name='health'),
    path('', views.home, name='home'),
    path('book/', views.book, name='book'),
    path('booking/<uuid:reference>/', views.confirmation, name='confirmation'),
    path('booking/<uuid:reference>/cancel/', views.cancel_booking, name='cancel_booking'),
    path('coordinator/', views.dashboard, name='dashboard'),
    path('coordinator/sign-in/', auth_views.LoginView.as_view(template_name='login.html'), name='login'),
    path('coordinator/sign-out/', auth_views.LogoutView.as_view(), name='logout'),
    path('coordinator/booking/<uuid:reference>/update/', views.update_booking, name='update_booking'),
    path('admin/', admin.site.urls),
    path('coordinator/integrations/', credential_views.integration_setup, name='integration_setup'),
    path('coordinator/booking/<uuid:reference>/credential/', credential_views.issue_credential, name='issue_credential'),
    path('credentials/<uuid:public_id>/', credential_views.verify_credential, name='verify_credential'),
    path('credentials/<uuid:public_id>/proof.json', credential_views.credential_proof, name='credential_proof'),
    path('credentials/<uuid:public_id>/revoke/', credential_views.revoke_credential, name='revoke_credential'),
    path('voice/audio/', credential_views.voice_audio, name='voice_audio'),
    path('learn/', community_views.learn, name='learn'),
    path('learn/<slug:lesson>/', community_views.learn, name='lesson'),
    path('neighbors/', neighbor_views.directory, name='neighbors'),
    path('neighbors/areas/', neighbor_views.area_search, name='neighbor_area_search'),
    path('neighbors/profile/', neighbor_views.my_profile, name='neighbor_profile'),
    path('neighbors/<uuid:neighbor_id>/introduce/', neighbor_views.introduce, name='neighbor_introduce'),
    path('coordinator/neighbors/', neighbor_views.moderate, name='neighbor_review'),
    path('coordinator/neighbors/maps/', neighbor_views.maps_setup, name='neighbor_maps_setup'),
    path('community/', community_views.hub, name='community_hub'),
    path('community/events/<slug:slug>/', community_views.event_detail, name='community_event'),
    path('community/events/<slug:slug>/attendance/', community_views.event_attendance, name='community_attendance'),
    path('community/albums/', community_views.albums, name='community_albums'),
    path('community/albums/<slug:slug>/', community_views.album_detail, name='community_album'),
    path('community/photos/upload/', community_views.upload_photo, name='community_upload'),
    path('community/photos/<uuid:photo_id>/', community_views.photo_detail, name='community_photo'),
    path('community/photos/<uuid:photo_id>/image/', community_views.photo_image, name='community_photo_image'),
    path('community/photos/<uuid:photo_id>/action/', community_views.photo_action, name='community_photo_action'),
    path('coordinator/community/', community_views.moderate_community, name='community_moderation'),
    path('coordinator/community/photos/<uuid:photo_id>/image/', community_views.moderation_image, name='community_moderation_image'),
]
