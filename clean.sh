#!/usr/bin/env bash
#
# Cleanup script for rubber docker workshop
#
# Move to root directory to avoid path issues
pushd /

sudo rm -rf ./containers/*
# First cleanup all processes in the cgroups
if [ -d "/sys/fs/cgroup/rubber_docker" ]; then
  for cgroup in /sys/fs/cgroup/rubber_docker/*; do
    if [ -d "$cgroup" ]; then
      # Move all processes to parent cgroup
      if [ -f "$cgroup/cgroup.procs" ]; then
        cat "$cgroup/cgroup.procs" 2>/dev/null | while read pid; do
          echo "$pid" >/sys/fs/cgroup/cgroup.procs 2>/dev/null
        done
      fi
      # Remove the cgroup directory
      rmdir "$cgroup" 2>/dev/null
    fi
  done
  # Remove the main rubber_docker cgroup
  rmdir /sys/fs/cgroup/rubber_docker 2>/dev/null
fi

# Unmount any remaining mounts
while grep -q workshop /proc/mounts; do
  mnt=$(grep workshop /proc/mounts | shuf | head -n1 | cut -f2 -d' ')
  sudo umount "$mnt" 2>/dev/null || sudo umount -l "$mnt" 2>/dev/null
done

popd || exit
