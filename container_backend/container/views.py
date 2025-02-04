import os
from django.views.decorators.csrf import csrf_exempt
import socket
from django.shortcuts import render, redirect
from .main import delete_container, run
from .form import ContainerForm, DeleteContainerForm
import threading


SOCKET_ADD = "/tmp/mysock.socket"
server_ready = threading.Event()


def home(request):
    return render(request, "home_page.html")


def start_unix_server():
    if os.path.exists(SOCKET_ADD):
        os.unlink(SOCKET_ADD)

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    print(f"Starting on {SOCKET_ADD}")
    server_ready.set()
    try:
        sock.bind(SOCKET_ADD)
        sock.listen(1)
        print("Server is listening...")

        while True:
            print("Waiting for connection...")
            conn, client_add = sock.accept()
            print(f"Received connection from {client_add}")

            try:
                while True:
                    data = conn.recv(108).decode("utf-8")
                    if not data:
                        break
                    print(f"Received: {data}")
                    if data == "create_server_done":
                        print("Container created")
            except Exception as e:
                print(f"Error: {e}")
            finally:
                conn.close()
    except Exception as e:
        print(f"Server error: {e}")


app_name = __package__.split(".")[0]
containers_created = []


def delete_container_view(request):
    if request.method == "GET":
        form = DeleteContainerForm()
        return render(request, "delete_container.html", {"form": form})

    else:
        form = DeleteContainerForm(request.POST)
        if form.is_valid():
            name = form.cleaned_data["name"]

            container_dir = os.path.join(os.getcwd(), app_name, "containers/")
            delete_container(name, container_dir)

            return render(request, "delete_container.html", {"form": form})


def execute_container(request):
    pass


def monitor_container(request):
    pass


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
            command = "/bin/bash"

            run(
                name,
                memory,
                memory_swap,
                cpu_share,
                user,
                image_name,
                image_dir,
                container_dir,
                command,
            )
            return render(request, "create_container.html", {"form": form})

    else:
        form = ContainerForm()

        return render(
            request,
            "create_container.html",
            {"form": form, "container_list": containers_created},
        )


threading.Thread(target=start_unix_server, daemon=True).start()
server_ready.wait()
