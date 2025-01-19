import os
import stat
import subprocess
import tarfile
import uuid
import sys
import click
import traceback
from functions import FuncTools

tools = FuncTools()

CLONE_NEWNS = 0x00020000
CLONE_NEWPID = 0x20000000
CLONE_NEWUTS = 0x04000000

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


def create_container_root(image_name, image_dir, container_id, container_dir):
    image_path = _get_image_path(image_name, image_dir)
    image_root = os.path.join(image_dir, image_name, "rootfs")

    assert os.path.exists(image_path), "unable to locate image %s" % image_name

    if not os.path.exists(image_root):
        os.makedirs(image_root)

    with tarfile.open(image_path) as t:
        members = [
            m
            for m in t.getmembers()
            if m.type not in (tarfile.CHRTYPE, tarfile.BLKTYPE)
        ]
        t.extractall(image_root, members=members)

    container_cow_rw = _get_container_path(container_id, container_dir, "cow_rs")
    container_cow_workdir = _get_container_path(
        container_id, container_dir, "cow_workdir"
    )
    container_rootfs = _get_container_path(container_id, container_dir, "rootfs")
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
            tools.mount("devpts", dev_pts, "devpts")

        makedev(dev_path)
    except Exception as e:
        print(f"Error setting up container: {e}", file=sys.stderr)
        raise


def contain(command, image_name, image_dir, container_id, container_dir):
    try:
        tools.sethostname(container_id)
        subprocess.run(["mount", "--make-rprivate", "/"], check=True)
    except subprocess.CalledProcessError as e:
        print(f"Failed to make root private: {e}", file=sys.stderr)
        raise

    new_root = create_container_root(image_name, image_dir, container_id, container_dir)
    print("Created a new root fs for our container: {}".format(new_root))
    _create_mount(new_root)
    old_root = os.path.join(new_root, "old_root")
    os.makedirs(old_root)

    tools.pivot_root(new_root, old_root)

    os.chdir("/")

    tools.umount("/old_root", 2)
    os.rmdir("/old_root")

    os.execvp(command[0], command)


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
    "--container-dir",
    help="Containers directory",
    default=os.path.join(dir, "containers/"),
)
@click.argument("command", required=True, nargs=-1)
def run(image_name, image_dir, container_dir, command):
    container_id = str(uuid.uuid4())

    flags = CLONE_NEWPID | CLONE_NEWNS | CLONE_NEWUTS
    tools.unshare(flags)
    pid = os.fork()
    # pid = tools.clone(
    #    contain(command, image_name, image_dir, container_id, container_dir), flags
    # )
    #
    if pid == 0:
        contain(command, image_name, image_dir, container_id, container_dir)

    _, status = os.waitpid(pid, 0)
    exit_code = os.WEXITSTATUS(status)
    print(f"Child process {pid} exited with status {exit_code}")


if __name__ == "__main__":
    cli()
