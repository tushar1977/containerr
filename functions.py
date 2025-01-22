import sys
import os
import subprocess
import ctypes
from constants import NR_pivot_root

libc = ctypes.CDLL("libc.so.6", use_errno=True)


class FuncTools:
    def pivot_root(self, new_root, put_old):
        new_root = new_root.encode("utf-8")
        put_old = put_old.encode("utf-8")
        result = libc.syscall(NR_pivot_root, new_root, put_old)
        if result != 0:
            print(f"pivot_root failed with error code {result}", file=sys.stderr)
            raise OSError(f"pivot_root failed: {os.strerror(ctypes.get_errno())}")
        else:
            print(
                f"Successfully changed root to {new_root} and moved old root to {put_old}."
            )

    def sethostname(self, new_name):
        result = libc.sethostname(new_name.encode("utf-8"), len(new_name))
        if result != 0:
            raise OSError("Failed to set hostname")

    def unshare(self, flags):
        if libc.unshare(flags) != 0:
            errno = ctypes.get_errno()
            raise OSError(errno, f"Failed to unshare: {os.strerror(errno)}")

    def umount(self, target, flags):
        ret = libc.umount2(target.encode(), flags)
        print(f"Successfully Unmounted {target}")
        if ret != 0:
            errno = ctypes.get_errno()
            raise OSError(errno, os.strerror(errno))

    def mount(self, source, target, fs_type, options=None):
        cmd = ["mount"]
        if fs_type:
            cmd.extend(["-t", fs_type])
        if options:
            cmd.extend(["-o", options])
        cmd.extend([source, target])

        try:
            subprocess.run(
                cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
        except subprocess.CalledProcessError as e:
            print(f"Failed to mount {source} to {target}: {e}", file=sys.stderr)
            raise
        pass
