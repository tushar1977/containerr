import os
import subprocess
from django.shortcuts import render
import socketio
import pty
import select
import termios
import fcntl
from . import main
import struct
import signal

sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*")
global_config = {}

fd = None
child_pid = None


def index(request):
    global global_config
    data = request.session["data"]
    global_config.update(data)
    return render(request, "terminal.html")


def set_winsize(fd, row, col, xpix=0, ypix=0):
    winsize = struct.pack("HHHH", row, col, xpix, ypix)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)


async def read_and_forward_pty_output():
    global fd
    max_read_bytes = 1024 * 20
    while True:
        await sio.sleep(0.01)
        if fd:
            try:
                timeout_sec = 0
                (data_ready, _, _) = select.select([fd], [], [], timeout_sec)
                if data_ready:
                    output = os.read(fd, max_read_bytes).decode()
                    await sio.emit("pty_output", {"output": output})
            except (OSError, TypeError) as e:
                print(f"Error reading from PTY: {e}")
                break
        else:
            print("Process killed")
            break


@sio.event
async def resize(sid, message):
    if fd:
        set_winsize(fd, message["rows"], message["cols"])


@sio.event
async def pty_input(sid, message):
    if fd:
        os.write(fd, message["input"].encode())


@sio.event
async def disconnect_request(sid):
    await sio.disconnect(sid)


app_name = __package__.split(".")[0]


@sio.event
async def connect(sid, environ):
    global fd, child_pid, global_config

    if child_pid:
        os.write(fd, b"\n")
        return

    try:
        child_pid, fd = pty.fork()
        if child_pid > 0:
            print(f"Spawned child process: {child_pid}")
            sio.start_background_task(read_and_forward_pty_output)
        else:
            main.run(
                global_config["name"],
                global_config["memory"],
                global_config["memory_swap"],
                global_config["cpu_share"],
                global_config["user"],
                global_config["image_name"],
                global_config["image_dir"],
                global_config["container_dir"],
                ["/bin/bash"],
            )

    except OSError as e:
        print(f"Error creating PTY: {e}")
        child_pid = None
        fd = None


@sio.event
async def disconnect(sid):
    global fd
    global child_pid

    if child_pid:
        try:
            os.kill(child_pid, signal.SIGKILL)
            os.wait()
        except OSError as e:
            print(f"Error killing process: {e}")
        finally:
            fd = None
            child_pid = None
            print("Client disconnected")
