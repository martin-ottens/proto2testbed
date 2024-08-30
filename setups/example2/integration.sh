#!/bin/bash

# Just to be safe here
ip link del ns3_em0 2>/dev/null || true
ip link del ns3_em1 2>/dev/null || true

ip tuntap add ns3_em0 mode tap
ip link set up dev ns3_em0
ip tuntap add ns3_em1 mode tap
ip link set up dev ns3_em1

cd /tmp/ns-3-dev
# ns-3 tap-bridges are started with "UseLocal", so they will attach to ns3_em{0,1}
./ns3 run emulator -- --routers=$ROUTERS

ip link del ns3_em0
ip link del ns3_em1
