import random
import iptc
import string
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


def get_bridge_ip(bridge_name):
    try:
        with IPDB() as ipdb:
            if bridge_name in ipdb.interfaces:
                bridge = ipdb.interfaces[bridge_name]

                if "ipaddr" in bridge:
                    return bridge["ipaddr"][0]["address"]
            return None
    except Exception as e:
        print(f"Error fetching IP for bridge {bridge_name}: {e}")
        return None


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


def rule_exists(table_name, chain_name, rule):
    table = iptc.Table(table_name)
    chain = iptc.Chain(table, chain_name)
    for existing_rule in chain.rules:
        if (
            existing_rule.src == rule.src
            and existing_rule.out_interface == rule.out_interface
            and existing_rule.target == rule.target
        ):
            return True
    return False


def configure_iptables(bridge_name, interface, container_subnet):
    try:
        table = iptc.Table(iptc.Table.NAT)
        chain = iptc.Chain(table, "POSTROUTING")
        rule = iptc.Rule()
        rule.src = container_subnet
        rule.out_interface = interface
        target = iptc.Target(rule, "MASQUERADE")
        rule.target = target

        chain.insert_rule(rule)

        table = iptc.Table(iptc.Table.FILTER)
        chain = iptc.Chain(table, "FORWARD")
        rule = iptc.Rule()
        rule.in_interface = bridge_name
        rule.out_interface = interface
        target = iptc.Target(rule, "ACCEPT")
        rule.target = target
        chain.insert_rule(rule)

        rule = iptc.Rule()
        rule.in_interface = interface
        rule.out_interface = bridge_name
        rule.state = "RELATED,ESTABLISHED"
        target = iptc.Target(rule, "ACCEPT")
        rule.target = target
        chain.insert_rule(rule)

        chain = iptc.Chain(table, "INPUT")
        rule = iptc.Rule()
        rule.in_interface = bridge_name
        target = iptc.Target(rule, "ACCEPT")
        rule.target = target

        chain.insert_rule(rule)
        chain = iptc.Chain(table, "OUTPUT")
        rule = iptc.Rule()
        rule.out_interface = bridge_name
        target = iptc.Target(rule, "ACCEPT")
        rule.target = target
        chain.insert_rule(rule)

        print("iptables rules configured successfully.")
    except Exception as e:
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


def container_network(netns_name, container_ip, veth_container, bridge_ip):
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

            ns.routes.add({"dst": "default", "gateway": bridge_ip}).commit()

        print(f"Configured network for {veth_container} in namespace {netns_name}.")
    except Exception as e:
        print(f"Error configuring network in namespace {netns_name}: {e}")
    finally:
        ipr.close()
