#!/usr/bin/env bash

set -e

cd $(dirname $(dirname $(readlink -f $0)))/firmware
./docker.sh deploy
