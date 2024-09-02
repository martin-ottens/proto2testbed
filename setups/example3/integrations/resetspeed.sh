#!/bin/bash

ethtool -s $INTERFACE autoneg on speed 1000 duplex full
