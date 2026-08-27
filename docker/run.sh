#!/bin/sh
# Every test in this repository, in a container. One command, one exit code.
#
#   docker/run.sh                 everything
#   docker/run.sh units sun       only those
#   docker/run.sh --list          what would run, and what would be skipped
#   docker/run.sh --skip-slow     leave out the ones that take minutes
#
# The repository is mounted rather than copied, so a change is tested without
# rebuilding anything. The image is rebuilt only when `docker/Dockerfile`
# changes; Docker's own layer cache decides that, and the first build takes a
# few minutes because it installs WeeWX.
set -eu

here=$(cd "$(dirname "$0")" && pwd)
repo=$(cd "$here/.." && pwd)
image=weewx-evo-tests

docker build -q -t "$image" -f "$here/Dockerfile" "$here" >/dev/null

# --read-only would be closer to right, but several of these write into the
# repository on purpose: the tracker files, the driver install, the rendered
# pages. They all clean up after themselves, and a test that cannot write is
# a test of the mount rather than of the code.
#
# No network. Every test here runs without one -- the forecast sources are
# checked against recorded responses, and the FTP and MQTT servers are
# started inside the test. A test that quietly reaches the internet is a test
# that fails on a train.
exec docker run --rm \
    --network none \
    -v "$repo:/repo" \
    -e TZ=Europe/Berlin \
    "$image" "$@"
