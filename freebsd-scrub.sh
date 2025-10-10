#!/bin/sh
# SPDX-License-Identifier: GPL-2.0-or-later
#
# clean up after an aborted topotato run

set -x

# zap all jails
jls | awk '{ if ($1 != "JID") print $1; }' | while read N; do jail -r $N; done

# umount everything, multiple tries
i=0
while mount | grep -E -q "/tmp/topo_"; do
	mount | grep /tmp/topo_ | awk '{ print $3; }' | while read N; do
		umount "$N"
	done

	: "$(( i = i + 1 ))"
	test $i -gt 5 && break
done

# zap remaining epair network devices
ifaces="$(ifconfig -a | awk '/flags=/ { split($1, a, ":"); printf "%s\n", a[1]; }' | grep -E -v '^vtnet|^lo')"
for iface in $ifaces; do
	ifconfig $iface destroy || redo=true
done
