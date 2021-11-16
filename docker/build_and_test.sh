#!/bin/bash
set -euf -o pipefail

if hash docker 2> /dev/null
then
  DOCKER_COMMAND=docker
else
  DOCKER_COMMAND=podman
fi

$DOCKER_COMMAND build -ti -t aleph-vm-supervisor -f docker/vm_supervisor.dockerfile .
$DOCKER_COMMAND run -ti --rm \
  -v $(pwd):/root/aleph-vm \
  --device /dev/kvm \
  -v /dev/kvm:/dev/kvm \
  --privileged \
  --name vm_supervisor \
  aleph-vm-supervisor \
  bash

#  pytest
#  python3 -m vm_supervisor -p -vv --system-logs --benchmark 1 --profile
