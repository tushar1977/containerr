import sys
import os
import subprocess

import ctypes

NR_pivot_root = 155
NR_CLONE = 56

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

    def clone(self, callback, flags=None, callback_arg=None) -> int:
        """
        Wrapper for the clone syscall.

        Args:
            callback: Function to be executed in the new process/thread
            flags: Clone flags (default: SIGCHLD)
            callback_arg: Optional argument to pass to the callback

        Returns:
            pid: Process ID of the new process/thread

        Raises:
            OSError: If clone fails
        """
        # Default to SIGCHLD if no flags specified for proper process management
        if flags is None:
            flags = 0x20000000  # SIGCHLD

        # Create callback function type
        c_callback = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p)(callback)

        # Allocate stack using mmap for better memory management
        STACK_SIZE = 8192  # 8KB stack

        # Using mmap to allocate stack memory
        stack = mmap.mmap(
            -1,
            STACK_SIZE,
            prot=mmap.PROT_READ | mmap.PROT_WRITE,
            flags=mmap.MAP_PRIVATE | mmap.MAP_ANONYMOUS,
        )

        # Stack grows downward, so point to the high address
        stack_top = ctypes.c_void_p(
            ctypes.addressof(ctypes.c_char.from_buffer(stack, 0)) + STACK_SIZE
        )

        # Prepare argument if provided
        if callback_arg is not None:
            c_arg = ctypes.c_void_p(callback_arg)
        else:
            c_arg = None

        try:
            # Call clone
            result = libc.clone(c_callback, stack_top, flags, c_arg)
            if result == -1:
                raise OSError(ctypes.get_errno(), "Clone failed")
            return result
        except:
            # Ensure stack is freed on error
            stack.close()
            raise

    def unshare(self, flags):
        if libc.unshare(flags) != 0:
            errno = ctypes.get_errno()
            raise OSError(errno, f"Failed to unshare: {os.strerror(errno)}")

    def umount(self, target, flags):
        cmd = ["umount"]
        cmd.append("-l")
        if target:
            cmd.append(target)
        if flags:
            cmd.append(flags)

        try:
            subprocess.run(
                cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
            print(f"Successfully unmounted {target}.")
        except subprocess.CalledProcessError as e:
            print(
                f"Failed to unmount {target}: {e.stderr.decode().strip()}",
                file=sys.stderr,
            )
            raise

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
