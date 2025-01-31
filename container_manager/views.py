import os
from django.core.management.base import BaseCommand
from django.views.decorators.csrf import csrf_exempt
import socket
from django.http import HttpResponse, JsonResponse, response
from django.shortcuts import render, redirect
from .main import run
from .form import ContainerForm
import threading

SOCKET_ADD = "/var/run/mysock.socket"


def start_unix_server():
    if os.path.exists(SOCKET_ADD):
        os.unlink(SOCKET_ADD)

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    print(f"Starting on {SOCKET_ADD}")
    sock.bind(SOCKET_ADD)
    sock.listen(1)

    while True:
        print("Waiting for connection...")
        conn, client_add = sock.accept()

        try:
            print(f"Received from {client_add}")

            while True:
                data = conn.recv(1024).decode("utf-8")

                if data == "create_server_done":
                    print("Container created")

        except Exception as e:
            print(f"Error {e}")
        finally:
            conn.close()


threading.Thread(target=start_unix_server, daemon=True).start()

app_name = __package__.split(".")[0]


@csrf_exempt
def create_container_view(request):
    if request.method == "POST":
        form = ContainerForm(request.POST)

        if form.is_valid():
            name = form.cleaned_data["name"]
            memory = form.cleaned_data["memory"]
            memory_swap = form.cleaned_data["memory_swap"]
            cpu_share = form.cleaned_data["cpu_share"]
            user = form.cleaned_data["user"]
            image_name = form.cleaned_data["image_name"]
            image_dir = os.path.join(os.getcwd(), app_name, "images/")
            container_dir = os.path.join(os.getcwd(), app_name, "containers/")

            code = run(
                name,
                memory,
                memory_swap,
                cpu_share,
                user,
                image_name,
                image_dir,
                container_dir,
            )
            if code == 0:
                return render(request, "create_container.html", {"form": form})

    else:
        form = ContainerForm()

    return render(request, "create_container.html", {"form": form})
