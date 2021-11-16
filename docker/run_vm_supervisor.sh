#!/bin/sh

# Use Podman if installed, else use Docker
if hash podman 2> /dev/null
then
  DOCKER_COMMAND=podman
else
  DOCKER_COMMAND=docker
fi

$DOCKER_COMMAND build -t alephim/vm-supervisor-dev -f docker/vm_supervisor-dev.dockerfile .

$DOCKER_COMMAND run -ti --rm \
  -v "$(pwd)/runtimes/aleph-debian-11-python/rootfs.squashfs:/opt/aleph-vm/runtimes/aleph-debian-11-python/rootfs.squashfs:ro" \
  -v "$(pwd)/examples/volumes/volume-venv.squashfs:/opt/aleph-vm/examples/volumes/volume-venv.squashfs:ro" \
  --device /dev/kvm \
  -p 4020:4020 \
  --privileged  \
  aleph-vm-supervisor-dev \
  bash
#  python3 -m vm_supervisor -p -vv --system-logs --benchmark 1 --profile
