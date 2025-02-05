from django.urls import include, path, re_path

from . import views, views_terminal

urlpatterns = [
    path("containers/create/", views.create_container_view, name="create_container"),
    path("containers/delete/", views.delete_container_view, name="delete_container"),
    path("containers/execute/", views.execute_container_view, name="execute_container"),
    path("containers/terminal/", views_terminal.index, name="terminal"),
    path("containers/monitor/", views.monitor_container, name="monitor_container"),
    path("", views.home, name="home page"),
]
