#!/bin/bash

if [ $# -eq 0 ]; then
    echo "Usage: $0 <FILENAME>"
    exit 1
fi

if [ ! -f "$1" ]; then
    echo "File $1 does not exist."
    exit 1
fi

for var in $(env | cut -d '=' -f 1); do
    temp_file=$(mktemp)
    value=$(printf '%s' "${!var}" | sed 's/[&/\]/\\&/g')

    sed "s|{{${var}}}|${value}|g" "$1" > "$temp_file"

    if ! cmp -s "$1" "$temp_file"; then
        echo "Placeholder {{${var}}} replaced by ${value}"
        mv "$temp_file" "$1"
    else
        rm "$temp_file"
    fi
done
