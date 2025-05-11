#!/bin/sh

# This script is provided to ensure builds of firmware included in the repository are byte for byte
# reproducible regardless of the host OS or the packages installed.
#
# Using this script is not a requirement to work on the firmware; installation instructions for
# the prerequisites for a selection of operating systems are included in the documentation.

BASE_IMAGE=debian:bookworm-slim

if [ -z "${DOCKER}" ]; then
    exec docker run \
        --volume $(dirname $(dirname $(readlink -f $0))):/glasgow \
        --workdir /glasgow \
        --env DOCKER=1 \
        --env UID=$(id -u) \
        --env GID=$(id -g) \
        --rm ${BASE_IMAGE} \
        software/deploy-firmware.sh
fi

set -ex

# Install dependencies.
apt-get update -qq
apt-get install -qq --no-install-recommends git make sdcc

# Any commands that create new files in the host mount must be invoked with the caller UID/GID, or
# else the created files will be owned by root. We can't use `docker run --user` because then
# apt-get would not be able to install packages.
#
# Create a user and a group with the UID/GID of the caller.
groupadd --gid ${GID} caller
useradd --uid ${UID} --gid ${GID} caller

# Do the work.
su caller - <<END

# Display dependency versions.
sdcc --version

# Clean all build products; they may have been built using a different compiler.
make -C vendor/libfx2/firmware/library clean
make -C firmware clean

# Build the artifact.
make -C vendor/libfx2/firmware/library all MODELS=medium
make -C firmware all

# Deploy the artifact.
cp firmware/glasgow.ihex software/glasgow/hardware/firmware.ihex

END
