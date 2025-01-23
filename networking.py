import random
import subprocess
import string


def generate_random_name(prefix, length=3):
    suffix = "".join(random.choices(string.digits, k=length))
    return f"{prefix}{suffix}"


def generate_random_ip(subnet):
    network, prefix = subnet.split("/")
    prefix = int(prefix)

    host_bits = 32 - prefix
    host = random.randint(1, (1 << host_bits) - 2)

    ip_parts = list(map(int, network.split(".")))
    for i in range(4):
        if host <= 0:
            break
        ip_parts[3 - i] |= host & 0xFF
        host >>= 8

    return f"{'.'.join(map(str, ip_parts))}/{prefix}"


def generate_gateway_ip(subnet):
    network, prefix = subnet.split("/")
    prefix = int(prefix)

    ip_parts = list(map(int, network.split(".")))
    ip_parts[3] += 1

    return f"{'.'.join(map(str, ip_parts))}"


subnet = "192.168.1.0/24"

bridge_name = "custom_bridge"
veth_host = generate_random_name("veth")
veth_container = generate_random_name("veth")
bridge_ip = generate_random_ip(subnet)
container_ip = generate_random_ip(subnet)
gateway_ip = generate_gateway_ip(subnet)


def create_bridge():
    subprocess.run(
        ["sudo", "ip", "link", "add", "name", bridge_name, "type", "bridge"],
        check=True,
    )
    subprocess.run(["sudo", "ip", "link", "set", bridge_name, "up"], check=True)

    subprocess.run(["sudo", "ip", "addr", "add", bridge_ip, "dev", bridge_name])


def enable_ip_forward():
    subprocess.run(
        ["sudo", "sh", "-c", "echo 'net.ipv4.ip_forward=1' >> /etc/sysctl.conf"],
        check=True,
    )
    subprocess.run(["sudo", "sysctl", "-p"], check=True)


def get_active_interface():
    try:
        result = subprocess.run(
            ["ip", "route", "get", "8.8.8.8"],
            capture_output=True,
            text=True,
            check=True,
        )
        for line in result.stdout.splitlines():
            if "dev" in line:
                return line.split("dev")[1].split()[0]
    except subprocess.CalledProcessError:
        print("Error: Could not determine the active network interface.")
    return None


def configure_iptables(bridge_name, interface):
    try:
        subprocess.run(
            [
                "sudo",
                "iptables",
                "-t",
                "nat",
                "-A",
                "POSTROUTING",
                "-o",
                interface,
                "-j",
                "MASQUERADE",
            ],
            check=True,
        )
        subprocess.run(
            [
                "sudo",
                "iptables",
                "-A",
                "FORWARD",
                "-i",
                bridge_name,
                "-o",
                interface,
                "-j",
                "ACCEPT",
            ],
            check=True,
        )
        subprocess.run(
            [
                "sudo",
                "iptables",
                "-A",
                "FORWARD",
                "-i",
                interface,
                "-o",
                bridge_name,
                "-m",
                "state",
                "--state",
                "RELATED,ESTABLISHED",
                "-j",
                "ACCEPT",
            ],
            check=True,
        )
        print("iptables rules configured successfully.")
    except subprocess.CalledProcessError as e:
        print(f"Error configuring iptables: {e}")


def create_veth_pair(veth_host, veth_container, bridge_name):
    try:
        subprocess.run(
            [
                "sudo",
                "ip",
                "link",
                "add",
                veth_host,
                "type",
                "veth",
                "peer",
                "name",
                veth_container,
            ],
            check=True,
        )
        print(f"Created veth pair: {veth_host} <--> {veth_container}")

        subprocess.run(["sudo", "ip", "link", "set", veth_host, "up"], check=True)
        subprocess.run(["sudo", "ip", "link", "set", veth_container, "up"], check=True)
        print(f"Interfaces {veth_host} is up.")

        subprocess.run(
            ["sudo", "ip", "link", "set", veth_host, "master", bridge_name],
            check=True,
        )
        print(f"Attached {veth_host} to bridge {bridge_name}.")

    except subprocess.CalledProcessError as e:
        print(f"Error configuring veth pair: {e}")


def move_veth(pid):
    subprocess.run(["sudo", "ip", "link", "set", veth_container, "netns", pid])


def container_network():
    try:
        subprocess.run(
            ["sudo", "ip", "addr", "add", container_ip, "dev", veth_container],
            check=True,
        )

        subprocess.run(
            ["sudo", "ip", "link", "set", veth_container, "up"],
            check=True,
        )

        subprocess.run(
            ["sudo", "ip", "route", "add", "default", "via", gateway_ip],
            check=True,
        )

    except subprocess.CalledProcessError as e:
        print(f"Error configuring container interface: {e}")
