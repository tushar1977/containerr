"""
WSGI config for container_backend project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.1/howto/deployment/wsgi/
"""

import os
import socketio
from django.core.asgi import get_asgi_application
from django_xterm_terminal.views import sio

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "container_backend.settings")
django_app = get_asgi_application()
application = socketio.ASGIApp(sio, django_app)
