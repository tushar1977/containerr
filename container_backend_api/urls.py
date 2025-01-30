from container_manager.views import create_container_view
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("container/", include("container_manage.urls")),
]
