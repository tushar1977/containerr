import os
from django.views.decorators.csrf import csrf_exempt
import socket
from django.http import response
from django.shortcuts import render, redirect
from .form import ContainerForm
import subprocess
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

            cli_command = [
                "sudo",
                "python3",
                "../main.py",
                "run",
                "--name",
                name,
                "--memory",
                memory,
                "--memory-swap",
                memory_swap,
                "--cpu-share",
                str(cpu_share),
                "--user",
                user,
                "--image-name",
                image_name,
            ]

            cli_command = [arg for arg in cli_command if arg]

            try:
                subprocess.Popen(cli_command, shell=True)
                return response.JsonResponse({"status": "done"})

            except Exception as e:
                return response.JsonResponse({"status": e})
    else:
        form = ContainerForm()

    return render(request, "create_container.html", {"form": form})
