import os
from pyroute2 import netns, NetNS, IPDB
from pyroute2.ndb.objects import json
from networking import (
    configure_iptables,
    container_network,
    create_bridge,
    create_namespace,
    create_veth_pair,
    enable_ip_forward,
    generate_gateway_ip,
    generate_random_ip,
    generate_random_name,
    get_active_interface,
    get_bridge_ip,
    move_veth,
)
import random
import stat
import subprocess
import tarfile
import uuid
import sys
import click
from functions import FuncTools
from constants import CLONE_NEWNS, CLONE_NEWPID, CLONE_NEWUTS, CLONE_NEWNET

tools = FuncTools()

subnet = "192.168.3.0/24"

bridge_name = "custom_bridge"
veth_host = generate_random_name("veth")
container_ip = generate_random_ip(subnet)
gateway_ip = generate_gateway_ip(subnet)
bridge_ip = get_bridge_ip(bridge_name)
if not bridge_ip:
    bridge_ip = generate_random_ip(subnet)


interface = get_active_interface()
dir = os.getcwd()


@click.group()
def cli():
    pass


def makedev(dev_path):
    for i, dev in enumerate(["stdin", "stdout", "stderr"]):
        os.symlink(f"/proc/self/fd/{i}", os.path.join(dev_path, dev))
    os.symlink("/proc/self/fd", os.path.join(dev_path, "fd"))
    DEVICES = {
        "null": (stat.S_IFCHR, 1, 3),
        "zero": (stat.S_IFCHR, 1, 5),
        "random": (stat.S_IFCHR, 1, 8),
        "urandom": (stat.S_IFCHR, 1, 9),
        "console": (stat.S_IFCHR, 136, 1),
        "tty": (stat.S_IFCHR, 5, 0),
        "full": (stat.S_IFCHR, 1, 7),
    }
    for device, (dev_type, major, minor) in DEVICES.items():
        os.mknod(
            os.path.join(dev_path, device), 0o666 | dev_type, os.makedev(major, minor)
        )


def _get_image_path(image_name, image_dir, image_suffix="tar"):
    return os.path.join(image_dir, os.extsep.join([image_name, image_suffix]))


def _get_container_path(container_id, container_dir, *subdir_names):
    return os.path.join(container_dir, container_id, *subdir_names)


def _setup_cpu_cgroup(container_id, cpu_shares):
    CGROUP_BASE = "/sys/fs/cgroup"
    RUBBER_DOCKER = os.path.join(CGROUP_BASE, "rubber_docker")
    container_cgroup = os.path.join(RUBBER_DOCKER, container_id)
    proc_file = os.path.join(container_cgroup, "cgroup.procs")

    if not os.path.exists(RUBBER_DOCKER):
        os.makedirs(RUBBER_DOCKER)

    subtree_control_file = os.path.join(RUBBER_DOCKER, "cgroup.subtree_control")
    if os.path.exists(subtree_control_file):
        with open(subtree_control_file, "w") as f:
            f.write("+cpu")

    os.makedirs(container_cgroup, exist_ok=True)

    if not os.path.exists(proc_file):
        open(proc_file, "w").close()

    with open(proc_file, "a") as f:
        f.write(str(os.getpid()))
    if cpu_shares:
        weight = max(1, min(10000, int(cpu_shares * 10000 / 1024)))
        cpu_weight_file = os.path.join(container_cgroup, "cpu.weight")
        print(f"Setting CPU weight to {weight} in {cpu_weight_file}")
        with open(cpu_weight_file, "w") as f:
            f.write(str(weight))


def _setup_memory_cgroup(container_id, memory, memory_swap):
    CGROUP_BASE = "/sys/fs/cgroup"
    container_mem_cgroup_dir = os.path.join(CGROUP_BASE, "rubber_docker", container_id)
    rubber_docker_dir = os.path.join(CGROUP_BASE, "rubber_docker")
    tasks_file = os.path.join(container_mem_cgroup_dir, "cgroup.procs")
    mem_limit_file = os.path.join(container_mem_cgroup_dir, "memory.max")

    if not os.path.exists(container_mem_cgroup_dir):
        os.makedirs(container_mem_cgroup_dir)

    with open(os.path.join(rubber_docker_dir, "cgroup.subtree_control"), "w") as f:
        f.write("+memory")

    with open(tasks_file, "w") as f:
        f.write(str(os.getpid()))

    if not os.path.exists(mem_limit_file):
        open(mem_limit_file, "w").close()

    if memory:
        with open(mem_limit_file, "w") as f:
            f.write(str(memory))

    if memory_swap:
        memsw_limit_file = os.path.join(container_mem_cgroup_dir, "memory.swap.max")
        with open(memsw_limit_file, "w") as f:
            f.write(str(memory_swap))


def create_container_root(
    image_name, image_dir, container_id, container_name, container_dir
):
    image_path = _get_image_path(image_name, image_dir)
    image_root = os.path.join(image_dir, image_name, "rootfs")

    if not os.path.exists(image_path):
        raise FileNotFoundError(f"Unable to locate image {image_name}")

    if not os.path.exists(image_root):
        os.makedirs(image_root)

    with tarfile.open(image_path) as t:
        members = [
            m
            for m in t.getmembers()
            if m.type not in (tarfile.CHRTYPE, tarfile.BLKTYPE)
        ]
        t.extractall(image_root, members=members)

    container_cow_rw = _get_container_path(
        f"{container_name}_{container_id}", container_dir, "cow_rs"
    )
    container_cow_workdir = _get_container_path(
        f"{container_name}_{container_id}", container_dir, "cow_workdir"
    )
    container_rootfs = _get_container_path(
        f"{container_name}_{container_id}", container_dir, "rootfs"
    )
    for d in (container_cow_rw, container_cow_workdir, container_rootfs):
        if not os.path.exists(d):
            os.makedirs(d)

    tools.mount(
        "overlay",
        container_rootfs,
        "overlay",
        "lowerdir={image_root},upperdir={cow_rw},workdir={cow_workdir}".format(
            image_root=image_root,
            cow_rw=container_cow_rw,
            cow_workdir=container_cow_workdir,
        ),
    )
    print(container_rootfs)
    return container_rootfs


def _unmount(new_root):
    proc_path = os.path.join(new_root, "proc")
    sys_path = os.path.join(new_root, "sys")
    dev_path = os.path.join(new_root, "dev")

    dev_pts = os.path.join(new_root, "dev", "pts")

    try:
        for d in (proc_path, sys_path, dev_path, dev_pts):
            if os.path.exists(d):
                tools.umount(d, 2)
    except Exception as e:
        print(e)


def _create_mount(new_root):
    proc_path = os.path.join(new_root, "proc")
    sys_path = os.path.join(new_root, "sys")
    dev_path = os.path.join(new_root, "dev")

    try:
        tools.mount("proc", proc_path, "proc")
        tools.mount("sysfs", sys_path, "sysfs")
        tools.mount("tmpfs", dev_path, "tmpfs", "mode=755,nosuid,strictatime")

        dev_pts = os.path.join(new_root, "dev", "pts")
        if not os.path.exists(dev_pts):
            os.makedirs(dev_pts)
            tools.mount("devpts", dev_pts, "devpts", "gid=5,mode=620")

        makedev(dev_path)

        new_sock = os.path.join(new_root, "var", "run", "mysock.socket")
        if not os.path.exists(new_sock):
            os.makedirs(new_sock)

        if os.path.exists("/var/run/mysock.socket"):
            tools.mount("/var/run/mysock.socket", new_sock, None, "bind")
            print("done binding ")

    except Exception as e:
        print(f"Error setting up container: {e}", file=sys.stderr)
        raise


def contain(
    command,
    image_name,
    image_dir,
    container_id,
    container_dir,
    cpu_shares,
    memory,
    memory_swap,
    user,
    container_name,
    netns_namespace,
    container_exist=False,
):
    if not container_exist:
        print(container_name)
        tools.setns(netns_namespace)
        _setup_cpu_cgroup(container_id, cpu_shares)
        _setup_memory_cgroup(container_id, memory, memory_swap)
        tools.sethostname(container_name)
        subprocess.run(["mount", "--make-rprivate", "/"], check=True)

        new_root = create_container_root(
            image_name, image_dir, container_id, container_name, container_dir
        )

        _create_mount(new_root)
        old_root = os.path.join(new_root, "old_root")
        os.makedirs(old_root)

        tools.pivot_root(new_root, old_root)

        os.chdir("/")

        tools.umount("/old_root", 2)
        os.rmdir("/old_root")

        if user:
            if ":" in user:
                uid, gid = user.split(":")
                uid = int(uid)
                gid = int(gid)
            else:
                uid = int(user)
                gid = uid

            os.setgid(gid)
            os.setuid(uid)

        with open("/etc/resolv.conf", "w") as f:
            f.write("nameserver 8.8.8.8")
        os.execvp(command[0], command)


@cli.command(
    context_settings=dict(
        ignore_unknown_options=True,
    )
)
@click.option(
    "--name",
    "-n",
    help="Gives name to containers",
    default=lambda: f"container{random.randint(1, 100)}",
)
@click.option(
    "--memory",
    "-m",
    help="Memory limit in bytes. Use suffixes to represent larger units (k, m, g)",
    default=None,
)
@click.option(
    "--memory-swap",
    help="A positive integer equal to memory plus swap."
    " Specify -1 to enable unlimited swap.",
    default=None,
)
@click.option("--cpu-share", "-c", help="CPU shares (relative weight)", default=0)
@click.option("--user", help="UID (format: <uid>:<gid>)", default="")
@click.option("--image-name", "-i", help="Image name", default="ubuntu")
@click.option(
    "--image-dir", help="Images directory", default=os.path.join(dir, "images/")
)
@click.option(
    "--container-dir",
    help="Containers directory",
    default=os.path.join(dir, "containers/"),
)
@click.argument("command", required=True, nargs=-1)
def run(
    name,
    memory,
    memory_swap,
    cpu_share,
    user,
    image_name,
    image_dir,
    container_dir,
    command,
):
    container_id = str(uuid.uuid4())

    veth_container = f"veth{container_id[0:5]}"
    create_bridge(bridge_name, bridge_ip)
    create_veth_pair(veth_host, veth_container, bridge_name)
    enable_ip_forward()
    configure_iptables(bridge_name, interface, subnet)

    netns_namespace = f"netns_{container_id}"
    create_namespace(netns_namespace)

    move_veth(netns_namespace, veth_container)

    container_network(netns_namespace, container_ip, veth_container, bridge_ip)

    flags = CLONE_NEWPID | CLONE_NEWNS | CLONE_NEWUTS
    tools.unshare(flags)

    pid = os.fork()
    if pid > 0:
        print(pid)
    if pid == 0:
        contain(
            command,
            image_name,
            image_dir,
            container_id,
            container_dir,
            cpu_share,
            memory,
            memory_swap,
            user,
            name,
            netns_namespace,
        )

        os._exit(0)

    _, status = os.waitpid(pid, 0)
    exit_code = os.WEXITSTATUS(status)
    print(f"Child process {pid} exited with status {exit_code}")


def check_container(container_dir, container_name):
    for dir_name in os.listdir(container_dir):
        if dir_name.startswith(f"{container_name}_"):
            parts = dir_name.split("_", 1)
            return True, parts[0], parts[1]

    return False, None, None


@cli.command(
    context_settings=dict(
        ignore_unknown_options=True,
    )
)
@click.option("--image-name", "-i", help="Image name", default="ubuntu")
@click.option(
    "--image-dir", help="Images directory", default=os.path.join(dir, "images/")
)
@click.option(
    "--name",
    "-n",
    help="Gives name to containers",
)
@click.option(
    "--container-dir",
    help="Containers directory",
    default=os.path.join(dir, "containers/"),
)
@click.argument("command", required=True, nargs=-1)
def exec(image_name, image_dir, name, container_dir, command):
    print(name)
    image_path = os.path.join(image_dir, f"{image_name}.tar")
    flag, name, id = check_container(container_dir, name)
    print(f"{name}_{id}")
    if not flag:
        print("Container not exisits")
        return

    container_path = os.path.join(container_dir, f"{name}_{id}")
    image_root = os.path.join(container_dir, container_path, "rootfs")

    if not os.path.exists(image_path):
        raise FileNotFoundError(f"Unable to locate image {image_name}")

    if not os.path.exists(image_root):
        os.makedirs(image_root)
    try:
        with tarfile.open(image_path) as t:
            members = [
                m
                for m in t.getmembers()
                if m.type not in (tarfile.CHRTYPE, tarfile.BLKTYPE)
            ]
            t.extractall(image_root, members=members)

            flags = CLONE_NEWPID | CLONE_NEWNS | CLONE_NEWUTS
            tools.unshare(flags)

            pid = os.fork()
            if pid > 0:
                print(pid)
            if pid == 0:
                _create_mount(image_root)

                old_root = os.path.join(image_root, "old_root")
                if not os.path.exists(old_root):
                    os.makedirs(old_root, exist_ok=True)
                print(image_root)

                os.chroot(image_root)
                os.chdir("/")
                os.execvp(command[0], command)
    except Exception as e:
        _unmount(image_root)
        print(e)


if __name__ == "__main__":
    cli()
