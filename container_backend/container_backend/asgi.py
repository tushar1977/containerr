"""
WSGI config for container_backend project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.1/howto/deployment/wsgi/
"""

import os
import socketio
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "container_backend.settings")
django_app = get_asgi_application()

from container.views_terminal import sio

application = socketio.ASGIApp(sio, django_app)
