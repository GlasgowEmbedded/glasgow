#!/usr/bin/env bash

# This script is provided to ensure builds of firmware are byte for byte
# reproducible regardless of the host OS or the packages installed.
#
# Using this script is not a requirement to work on the firmware; installation instructions for
# the prerequisites for a selection of operating systems are included in the documentation.

set -e

MYUID=$(id -u)
MYGID=$(id -g)
TAG=glasgow_firmware_builder_${MYUID}_${MYGID}
GLASGOW_FOLDER=$(dirname $(dirname $(readlink -f $0)))

DOCKERFILE=$(cat <<-'EOF'
	FROM debian:trixie-20250721-slim@sha256:cc92da07b99dd5c078cb5583fdb4ba639c7c9c14eb78508a2be285ca67cc738a

	ARG UID
	ARG GID

	RUN DEBIAN_FRONTEND="noninteractive" apt-get update -qq && \
	    DEBIAN_FRONTEND="noninteractive" apt-get install -qq --no-install-recommends git make sdcc python3 python3-usb1 && \
	    rm -rf /var/lib/apt/lists/*

	# Any commands that create new files in the host mount must be invoked with the caller UID/GID, or
	# else the created files will be owned by root.
	#
	# Create a user and a group with the UID/GID of the caller.
	RUN groupadd --gid ${GID} caller || true
	RUN useradd --uid ${UID} --gid ${GID} caller

	USER caller
EOF
)

docker_run() {
	BARGS=""
	RARGS=""
	while [[ $# -gt 0 ]]; do
		if [ "--buildargs" = "$1" ]; then
			shift
			BARGS="$1"
			shift
		elif [ "--runargs" = "$1" ]; then
			shift
			RARGS="$1"
			shift
		else
			break
		fi
	done
	docker build $BARGS -t $TAG --build-arg GID=$MYGID --build-arg UID=$MYUID - <<< ${DOCKERFILE}
	docker run \
	    -i $RARGS \
	    --volume ${GLASGOW_FOLDER}:/glasgow \
	    --workdir /glasgow \
	    --rm $TAG \
	    "$@"
}

printusage() {
	echo "Usage: $0 COMMAND"
	echo ""
	echo "Commands:"
	echo "    clean - clean both libfx2 and firmware"
	echo "    build - build both libfx2 and firmware"
	echo "    rebuild - clean and build"
	echo "    deploy - rebuild and deploy to software/glasgow/hardware/firmware.ihex"
	echo "    load - load the newly built firmware into FX2 RAM"
	echo "    bash - launch an interactive bash shell inside docker"
}

if [ $# -lt 1 ]; then
	printusage
	exit -1
fi

if [ "clean" = "$1" ]; then
	docker_run /bin/bash -s -x <<-'EOF'
		set -e
		make -C vendor/libfx2/firmware/library clean
		make -C firmware clean
	EOF
elif [ "build" = "$1" ]; then
	docker_run /bin/bash -s -x <<-'EOF'
		set -e
		make -C vendor/libfx2/firmware/library all MODELS=medium
		make -C firmware all
	EOF
elif [ "rebuild" = "$1" ]; then
	docker_run /bin/bash -s -x <<-'EOF'
		set -e
		make -C vendor/libfx2/firmware/library clean
		make -C firmware clean
		make -C vendor/libfx2/firmware/library all MODELS=medium
		make -C firmware all
	EOF
elif [ "deploy" = "$1" ]; then
	docker_run --buildargs "--no-cache --progress=plain" /bin/bash -s -x <<-'EOF'
		set -e
		
		# Display dependency versions.
		sdcc --version
		
		# Clean all build products; they may have been built using a different compiler.
		make -C vendor/libfx2/firmware/library clean
		make -C firmware clean
		
		# Build the artifact.
		make -C vendor/libfx2/firmware/library all MODELS=medium
		make -C firmware all
		
		# Deploy the artifact. For incomprehensible (literally; I could not figure out why) reasons,
		# the Debian and NixOS builds of exact same commit of sdcc produce different .ihex files that
		# nevertheless translate to the same binary contents.
		PYTHONPATH=vendor/libfx2/software python3 firmware/normalize.py \
		    firmware/glasgow.ihex software/glasgow/hardware/firmware.ihex
	EOF
elif [ "load" = "$1" ]; then
	docker_run --runargs "--privileged -v /dev/bus/usb:/dev/bus/usb" /bin/bash -s -x <<-'EOF'
		set -e
		make -C firmware load
	EOF
elif [ "bash" = "$1" ]; then
	docker_run --runargs "--privileged -v /dev/bus/usb:/dev/bus/usb -t" /bin/bash
else
	printusage
	echo "Unknown command $1"
	exit -2
fi
