from django.shortcuts import render
import os
import socket

SOCKET_PATH = "/var/custom_container.socket"


def create_container(request):
    pass


def unix_socket():
    if os.path.exists(SOCKET_PATH):
        os.remove(SOCKET_PATH)

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(SOCKET_PATH)
    server.listen(5)

    while True:
        conn, _ = server.accept()
        data = conn.recv(1024).decode()
        if data == "/create_container":
            resp = create_container()
            conn.sendall(str(resp.content).encode())
        conn.close()
