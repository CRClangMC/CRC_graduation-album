
from django.urls import path, include
urlpatterns = [
    # 指向index的路由文件urls.py
    path('', include(('index.urls', 'index'), namespace='index')),

]