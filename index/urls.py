from django.urls import path
from django.views.static import serve
from django.conf import settings
from . import views

app_name = 'index'

urlpatterns = [
    path('', views.home, name='home'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('register/', views.register, name='register'),
    path('face_recognition/', views.face_recognition, name='face_recognition'),
    path('recognize_face/', views.recognize_face, name='recognize_face'),
    path('my_uploads/', views.my_uploads, name='my_uploads'),
    path('photo_upload/', views.photo_upload, name='photo_upload'),
    path('videos/', views.video_gallery, name='videos'),
    path('videos/preview/<str:file_id>/', views.video_preview, name='video_preview'),
    path('videos/watch/<str:file_id>/', views.watch_video, name='watch_video'),
    path('upload/', views.upload_video, name='upload_video'),
    path('api/vdo', views.vdo_list_api, name='vdo_list_api'),
    path('delete/', views.delete_files, name='delete_files'),
    path('api/search', views.search_files, name='search_files'),
    path('upload_chunk/', views.upload_chunk, name='upload_chunk'),
    path('merge_chunks/', views.merge_chunks, name='merge_chunks'),
    path('static/<path:path>', serve, {'document_root': settings.STATIC_ROOT}, name='static'),
    path('media/<path:path>', views.media_serve, name='media'),
]
