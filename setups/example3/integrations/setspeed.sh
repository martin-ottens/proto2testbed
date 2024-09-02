#!/bin/bash

ethtool -s $INTERFACE autoneg off speed 100 duplex full
