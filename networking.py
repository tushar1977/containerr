import random
import string
import subprocess
from pyroute2 import IPDB, IPRoute, netns
from pyroute2.nslink.nslink import NetNS


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


def create_bridge(bridge_name, bridge_ip):
    ipr = IPRoute()
    try:
        if not ipr.link_lookup(ifname=bridge_name):
            ipr.link("add", ifname=bridge_name, kind="bridge")
            ipr.link("set", index=ipr.link_lookup(ifname=bridge_name)[0], state="up")
            ipr.addr(
                "add",
                index=ipr.link_lookup(ifname=bridge_name)[0],
                address=bridge_ip.split("/")[0],
                mask=int(bridge_ip.split("/")[1]),
            )
            print(f"Created bridge {bridge_name} with IP {bridge_ip}.")
        else:
            print(f"Bridge {bridge_name} already exists.")
    except Exception as e:
        print(f"Error creating bridge: {e}")
    finally:
        ipr.close()


def enable_ip_forward():
    try:
        with open("/proc/sys/net/ipv4/ip_forward", "w") as f:
            f.write("1")
        print("Enabled IP forwarding.")
    except Exception as e:
        print(f"Error enabling IP forwarding: {e}")


def get_active_interface():
    ipr = IPRoute()
    try:
        routes = ipr.get_routes(dst="8.8.8.8")
        if routes:
            return ipr.get_links(routes[0].get_attr("RTA_OIF"))[0].get_attr(
                "IFLA_IFNAME"
            )
    except Exception as e:
        print(f"Error determining active network interface: {e}")
    finally:
        ipr.close()
    return None


def configure_iptables(bridge_name, interface, container_subnet):
    try:
        # Add NAT rule to masquerade traffic from the container subnet
        subprocess.run(
            [
                "sudo",
                "iptables",
                "-t",
                "nat",
                "-A",
                "POSTROUTING",
                "-s",
                container_subnet,
                "-o",
                interface,
                "-j",
                "MASQUERADE",
            ],
            check=True,
        )

        # Allow forwarding from the bridge to the external interface
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

        # Allow forwarding for established and related connections
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
    ipr = IPRoute()
    try:
        ipr.link("add", ifname=veth_host, peer=veth_container, kind="veth")

        host_index = ipr.link_lookup(ifname=veth_host)[0]
        ipr.link("set", index=host_index, state="up")

        bridge_index = ipr.link_lookup(ifname=bridge_name)[0]
        ipr.link("set", index=host_index, master=bridge_index)

        print(f"Created veth pair: {veth_host} <--> {veth_container}")
        print(f"Attached {veth_host} to bridge {bridge_name}.")
    except Exception as e:
        print(f"Error creating veth pair or attaching to bridge: {e}")
    finally:
        ipr.close()


def create_namespace(name):
    try:
        netns.create(name)
        print(f"Created network namespace: {name}")
    except Exception as e:
        print(f"Error creating network namespace {name}: {e}")


def move_veth(netns_name, veth_container):
    try:
        with IPDB() as ipdb:
            if veth_container not in ipdb.interfaces:
                raise ValueError(f"Interface {veth_container} does not exist.")

            with ipdb.interfaces[veth_container] as veth_container_if:
                veth_container_if.net_ns_fd = netns_name
                print(f"Moved {veth_container} to namespace {netns_name}.")
    except Exception as e:
        print(f"Error moving {veth_container} to namespace {netns_name}: {e}")


def container_network(netns_name, container_ip, veth_container, gateway_ip):
    ipr = IPRoute()
    try:
        with IPDB(nl=NetNS(netns_name)) as ns:
            with ns.interfaces.lo as lo:
                lo.up()

            if veth_container not in ns.interfaces:
                raise ValueError(
                    f"Interface {veth_container} does not exist in namespace {netns_name}."
                )

            with ns.interfaces[veth_container] as veth_container_if:
                veth_container_if.add_ip(container_ip)
                veth_container_if.up()

            ns.routes.add({"dst": "default", "gateway": gateway_ip}).commit()

        print(f"Configured network for {veth_container} in namespace {netns_name}.")
    except Exception as e:
        print(f"Error configuring network in namespace {netns_name}: {e}")
    finally:
        ipr.close()
