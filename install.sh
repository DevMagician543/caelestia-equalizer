#!/usr/bin/env bash
set -euo pipefail

if (( EUID == 0 )); then
    echo 'Run ./install.sh as your normal desktop user, not with sudo.' >&2
    exit 1
fi
if ! command -v python3 >/dev/null 2>&1; then
    if [[ " $* " == *' --no-packages '* ]] || ! command -v pacman >/dev/null 2>&1; then
        echo 'Python 3 is required. Install it, then run ./install.sh again.' >&2
        exit 1
    fi
    sudo pacman -S --needed python
fi
installer_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
exec python3 "$installer_dir/install.py" "$@"
