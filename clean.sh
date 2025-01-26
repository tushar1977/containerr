#!/usr/bin/env bash
#
# Cleanup script for rubber docker workshop
#

# Variables
BRIDGE_NAME="custom_bridge"
CONTAINER_SUBNET="192.168.1.0/24"
EXTERNAL_INTERFACE="wlp0s20f3" # Replace with your external interface

# Move to root directory to avoid path issues
pushd /

# Clean up containers directory
sudo rm -rf ./containers/*

# Clean up cgroups
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

# Function to remove veth pairs
remove_veth_pairs() {
  echo "Removing veth pairs..."
  for veth in $(ip link show | grep -oE 'veth[0-9]+@'); do
    veth=${veth%@} # Remove the '@' suffix
    echo "Deleting veth pair: $veth"
    ip link delete "$veth" 2>/dev/null
  done
}

# Function to remove the custom bridge
remove_bridge() {
  echo "Removing bridge: $BRIDGE_NAME..."
  if ip link show "$BRIDGE_NAME" >/dev/null 2>&1; then
    ip link set "$BRIDGE_NAME" down
    ip link delete "$BRIDGE_NAME"
    echo "Bridge $BRIDGE_NAME removed."
  else
    echo "Bridge $BRIDGE_NAME does not exist."
  fi
}

# Function to remove network namespaces
remove_network_namespaces() {
  echo "Removing network namespaces..."
  for ns in $(ip netns list | grep -oE 'netns_[a-f0-9-]+'); do
    echo "Deleting network namespace: $ns"
    ip netns delete "$ns"
  done
}

# Main cleanup function
cleanup() {
  remove_veth_pairs
  remove_bridge
  remove_network_namespaces
  echo "Network cleanup complete."
}

# Run cleanup
cleanup

# Return to the original directory
popd || exit
