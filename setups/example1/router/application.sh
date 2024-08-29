#!/bin/bash

tc qdisc add dev $INTERFACE root netem delay ${DELAY_MS}ms 0ms
