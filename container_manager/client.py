import socket
import sys

sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)

server_address = "/var/run/mysock.socket"
print("connecting to {}".format(server_address))
try:
    sock.connect(server_address)
except socket.error as msg:
    print(msg)
    sys.exit(1)

try:
    message = b"This is the message.  It will be repeated."
    print("sending {!r}".format(message))
    sock.sendall(message)

    amount_received = 0
    amount_expected = len(message)

    while amount_received < amount_expected:
        data = sock.recv(160)
        amount_received += len(data)
        print("received {!r}".format(data))

finally:
    print("closing socket")
    sock.close()
