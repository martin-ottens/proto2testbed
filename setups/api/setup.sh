#!/bin/bash

ip a a $IP_ADDRESS dev eth1
ip l s up dev eth1
