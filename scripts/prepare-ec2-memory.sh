#!/bin/bash
# Keep cold API/tester pages from forcing continuous executable/file reclaim on
# the shared 1 GiB demo host. This uses existing disk, not another AWS resource.
set -euo pipefail
swap_file=/opt/workbook-host.swap
if [ ! -e "$swap_file" ]; then
    available_kib=$(df -Pk /opt | awk 'NR==2 {print $4}')
    if [ "$available_kib" -lt 2097152 ]; then
        echo 'At least 2 GiB free disk is required before reserving 1 GiB swap.' >&2
        exit 1
    fi
    (umask 077; fallocate -l 1G "$swap_file")
    chmod 600 "$swap_file"
    mkswap "$swap_file"
fi
if [ -L "$swap_file" ] || [ ! -f "$swap_file" ]; then
    echo 'Unexpected swap file type; refusing to use it.' >&2
    exit 1
fi
chown root:root "$swap_file"
chmod 600 "$swap_file"
if ! swapon --show=NAME --noheadings | grep -Fxq "$swap_file"; then
    swapon "$swap_file"
fi
if ! awk -v file="$swap_file" '$1 == file && $3 == "swap" {found=1} END {exit !found}' /etc/fstab; then
    printf '%s none swap sw 0 0\n' "$swap_file" >> /etc/fstab
fi
printf 'vm.swappiness=20\n' > /etc/sysctl.d/90-workbook-memory.conf
sysctl -p /etc/sysctl.d/90-workbook-memory.conf
free -m
