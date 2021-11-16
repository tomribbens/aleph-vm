#!/bin/sh

set -euf

podman build -t aleph-connector -f docker/vm_connector.dockerfile .

podman run -ti --rm -p 4021:4021/tcp \
  -v "$(pwd)/kernels:/opt/kernels:ro" \
  -v "$(pwd)/vm_connector:/opt/vm_connector:ro" \
  --name aleph-connector \
  aleph-connector "$@"
