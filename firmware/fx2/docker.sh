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
GLASGOW_FOLDER=$(dirname $(dirname $(dirname $(readlink -f $0))))

DOCKERFILE=$(cat <<-'EOF'
	FROM nixos/nix:2.32.8@sha256:72a13b0f42e3cc515945aa4250b772381d93c96d4bf93aa950b5c68defdab1dd

	ARG UID
	ARG GID

	# Break the /etc/ symlinks so that we can add a user/group. I'm not happy about it either.
	RUN for file in group passwd shadow; do \
		  cp --remove-destination $(readlink /etc/$file) /etc/$file; \
		done

	# Ensure passwd and shadow are writable.
	RUN chmod u+w /etc/{passwd,shadow}

	# Any commands that create new files in the host mount must be invoked with the caller UID/GID, or
	# else the created files will be owned by root.
	#
	# Create a user and a group with the UID/GID of the caller.
	RUN nix-shell -p shadow --run "groupadd --gid ${GID} caller"
	RUN nix-shell -p shadow --run "useradd -m --uid ${UID} --gid ${GID} caller"

	RUN nix-channel --remove nixpkgs

	# The nixpkgs commit to pin to. Currently nixos-26.11pre with sdcc 4.6.0.
	ENV NIXPKGS_COMMIT=e554fab72f81915600f3f449b786fd9af40439a5
	ENV NIX_PATH=nixpkgs=https://github.com/NixOS/nixpkgs/archive/${NIXPKGS_COMMIT}.tar.gz

	# Install dependencies.
	RUN nix-env -f '<nixpkgs>' -iA gcc-arm-embedded-14 gnumake
	# There's a conflicting file between gcc-arm-embedded and sdcc.
	RUN nix-env --set-flag priority 0 gcc-arm-embedded
	RUN nix-env -f '<nixpkgs>' -iA sdcc
	RUN nix-env -i -E '_: with import <nixpkgs> {}; python3.withPackages (ps: [ ps.libusb1 ])'

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
	echo "    deploy - rebuild and deploy to software/glasgow/hardware/firmware-fx2.ihex"
	echo "    load - load the newly built firmware into FX2 RAM"
	echo "    bash - launch an interactive bash shell inside docker"
}

if [ $# -lt 1 ]; then
	printusage
	exit -1
fi

if [ "clean" = "$1" ]; then
	docker_run /bin/sh -s -x <<-'EOF'
		set -e
		make -C vendor/libfx2/firmware/library clean
		make -C firmware/fx2 clean
		make -C firmware/stm32 clean
	EOF
elif [ "build" = "$1" ]; then
	docker_run /bin/sh -s -x <<-'EOF'
		set -e
		make -C vendor/libfx2/firmware/library all MODELS=small
		make -C firmware/fx2 all
		make -C firmware/stm32 all
	EOF
elif [ "rebuild" = "$1" ]; then
	docker_run /bin/sh -s -x <<-'EOF'
		set -e

		make -C vendor/libfx2/firmware/library clean
		make -C firmware/fx2 clean
		make -C firmware/stm32 clean

		make -C vendor/libfx2/firmware/library all MODELS=small
		make -C firmware/fx2 all
		make -C firmware/stm32 all
	EOF
elif [ "deploy" = "$1" ]; then
	docker_run --buildargs "--no-cache --progress=plain" /bin/sh -s -x <<-'EOF'
		set -e

		# Display dependency versions.
		sdcc --version
		arm-none-eabi-gcc --version

		# Clean all build products; they may have been built using a different compiler.
		make -C vendor/libfx2/firmware/library clean
		make -C firmware/fx2 clean
		make -C firmware/stm32 clean

		# Build the artifact.
		make -C vendor/libfx2/firmware/library all MODELS=small
		make -C firmware/fx2 all
		make -C firmware/stm32 all

		PYTHONPATH=vendor/libfx2/software python3 firmware/fx2/normalize.py \
		    firmware/fx2/firmware.ihex software/glasgow/hardware/firmware-fx2.ihex
		cp firmware/stm32/firmware.bin software/glasgow/hardware/firmware-stm32.bin
	EOF
elif [ "load" = "$1" ]; then
	docker_run --runargs "--privileged -v /dev/bus/usb:/dev/bus/usb" /bin/sh -s -x <<-'EOF'
		set -e
		make -C firmware/fx2 load
	EOF
elif [ "bash" = "$1" ]; then
	docker_run --runargs "--privileged -v /dev/bus/usb:/dev/bus/usb -t" /bin/sh
else
	printusage
	echo "Unknown command $1"
	exit -2
fi
