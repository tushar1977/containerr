from django.urls import path

from . import views

urlpatterns = [
    path("containers/create/", views.create_container_view, name="create_container"),
    path("containers/delete/", views.delete_container, name="delete_container"),
    path("containers/execute/", views.execute_container, name="execute_container"),
    path("containers/monitor/", views.monitor_container, name="monitor_container"),
    path("", views.home, name="home page"),
]
