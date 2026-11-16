#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 KJaebye
set -eu

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
installer_python=${DOMINO_PYTHON:-python3}

# Help and offline bundles need no dependency downloads or temporary environment.
for argument in "$@"; do
    case "$argument" in
        -h|--help|--bundle|--bundle=*)
            exec "$installer_python" "$project_dir/domino_install.py" "$@"
            ;;
    esac
done

installer_work=$(mktemp -d "${TMPDIR:-/tmp}/domino-installer.XXXXXXXX")
trap 'rm -rf -- "$installer_work"' EXIT HUP INT TERM
"$installer_python" -m venv "$installer_work/venv"
"$installer_work/venv/bin/python" -m pip install --disable-pip-version-check --quiet "$project_dir"
"$installer_work/venv/bin/python" -m domino_install "$@"
