import os
import grp
import sys
import time
from django.shortcuts import render
import socketio
import pty
import select
import termios
import fcntl
import tty
import pwd
from . import main
import struct
import signal

sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*")

fd = None
child_pid = None
global_config = {}


def index(request):
    global global_config
    data = request.session["data"]
    global_config.update(data)
    return render(request, "terminal.html")


def set_winsize(fd, row, col, xpix=0, ypix=0):
    winsize = struct.pack("HHHH", row, col, xpix, ypix)
    try:
        fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)
    except IOError as e:
        debug_print(f"Failed to set window size: {e}")


def debug_print(message):
    """Print debug message with timestamp and process info"""
    print(f"[DEBUG] [PID:{os.getpid()}] [UID:{os.getuid()}] {message}")


def safe_setsid():
    """Attempt to create new session safely"""
    try:
        os.setsid()
        debug_print("Successfully created new session")
        return True
    except OSError as e:
        debug_print(f"setsid failed (continuing anyway): {e}")
        return False


def get_current_permissions():
    """Get current process permissions and group info"""
    try:
        username = pwd.getpwuid(os.getuid()).pw_name
        groups = [g.gr_name for g in [pwd.getgrgid(gid) for gid in os.getgroups()]]
        return f"User: {username}, UID: {os.getuid()}, GID: {os.getgid()}, Groups: {groups}"
    except Exception as e:
        return f"Error getting permissions: {e}"


async def read_and_forward_pty_output():
    global fd, child_pid
    max_read_bytes = 1024 * 20

    debug_print("Starting read_and_forward_pty_output")
    last_error_time = 0

    while True:
        await sio.sleep(0.01)
        if fd and child_pid:
            try:
                # Check if child process is still running
                try:
                    os.kill(child_pid, 0)
                except OSError:
                    debug_print("Child process no longer exists")
                    break

                timeout_sec = 0
                (data_ready, _, _) = select.select([fd], [], [], timeout_sec)
                if data_ready:
                    output = os.read(fd, max_read_bytes).decode(errors="replace")
                    debug_print(f"Read {len(output)} bytes from PTY")
                    await sio.emit("pty_output", {"output": output})
            except (OSError, TypeError) as e:
                # Rate limit error messages
                current_time = time.time()
                if current_time - last_error_time > 1:  # Log at most once per second
                    debug_print(f"Error reading from PTY: {e}")
                    last_error_time = current_time
                if isinstance(e, OSError) and e.errno == 5:  # Input/output error
                    break
        else:
            debug_print("PTY no longer available")
            break

    debug_print("Exiting read_and_forward_pty_output")


@sio.event
async def disconnect(sid):
    global fd, child_pid

    debug_print("Handling disconnect")
    if child_pid:
        try:
            os.kill(child_pid, signal.SIGTERM)
            try:
                os.waitpid(child_pid, 0)
            except OSError:
                pass
        except OSError as e:
            debug_print(f"Error killing process: {e}")
        finally:
            fd = None
            child_pid = None
            debug_print("Client disconnected")


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


def detach_controlling_tty():
    debug_print("Attempting to detach controlling TTY")
    try:
        fd = os.open("/dev/tty", os.O_RDWR | os.O_NOCTTY)
        debug_print(f"Opened /dev/tty with fd: {fd}")
        try:
            fcntl.ioctl(fd, termios.TIOCNOTTY, "")
            debug_print("Successfully detached controlling TTY")
        except Exception as e:
            debug_print(f"Failed to detach TTY with ioctl: {e}")
        finally:
            os.close(fd)
    except OSError as e:
        debug_print(f"Failed to open /dev/tty: {e}")


def attach_controlling_tty(fd):
    debug_print(f"Attempting to attach controlling TTY to fd: {fd}")
    try:
        fcntl.ioctl(fd, termios.TIOCSCTTY, 0)
        debug_print("Successfully attached controlling TTY")
    except OSError as e:
        debug_print(f"Failed to attach controlling TTY: {e}")


@sio.event
async def connect(sid, environ):
    global fd, child_pid, global_config

    debug_print("Starting connect handler")

    if child_pid:
        debug_print(f"Existing child process found: {child_pid}")
        return

    try:
        debug_print("Attempting to fork PTY")
        child_pid, fd = pty.fork()

        if child_pid == 0:
            # Child process
            debug_print("In child process")
            try:
                # Print child process environment
                debug_print(f"Child process environment: {os.environ}")
                debug_print(f"Current working directory: {os.getcwd()}")

                # Try to create new session
                try:
                    os.setsid()
                    debug_print("Successfully created new session")
                except OSError as e:
                    debug_print(f"setsid failed (continuing): {e}")

                # Set up terminal
                try:
                    attr = termios.tcgetattr(sys.stdin.fileno())
                    attr[3] = attr[3] & ~termios.ECHO
                    termios.tcsetattr(sys.stdin.fileno(), termios.TCSANOW, attr)
                    debug_print("Terminal attributes set successfully")
                except termios.error as e:
                    debug_print(f"Failed to set terminal attributes (continuing): {e}")

                debug_print("Starting main.run with config:")
                debug_print(f"  name: {global_config['name']}")
                debug_print(f"  command: {global_config['command']}")
                debug_print(f"  image: {global_config['image_name']}")

                main.run(
                    global_config["name"],
                    global_config["memory"],
                    global_config["memory_swap"],
                    global_config["cpu_share"],
                    global_config["user"],
                    global_config["image_name"],
                    global_config["image_dir"],
                    global_config["container_dir"],
                    [global_config["command"]],
                )
            except Exception as e:
                debug_print(f"Error in child process: {e}")
                debug_print(f"Traceback: {traceback.format_exc()}")
                sys.exit(1)
        else:
            # Parent process
            debug_print(f"In parent process. Child PID: {child_pid}")
            try:
                # Set up the PTY
                attr = termios.tcgetattr(fd)
                attr[3] = attr[3] & ~termios.ICANON & ~termios.ECHO
                termios.tcsetattr(fd, termios.TCSANOW, attr)
                debug_print("PTY attributes set successfully")

                # Set initial window size
                set_winsize(fd, 24, 80)
                debug_print("Window size set")

                debug_print("Starting output reader task")
                sio.start_background_task(read_and_forward_pty_output)

                await sio.emit(
                    "pty_output", {"output": "Terminal connected successfully\n"}
                )
                debug_print("Connection setup completed successfully")
            except Exception as e:
                debug_print(f"Error setting up parent process: {e}")
                raise

    except OSError as e:
        error_msg = f"Error creating PTY: {e}"
        debug_print(f"Fatal error: {error_msg}")
        await sio.emit("pty_output", {"output": f"Error: {error_msg}\n"})
        child_pid = None
        fd = None
