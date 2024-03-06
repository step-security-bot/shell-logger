#!/usr/bin/env bash
ORIG_DIR=$(pwd)
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)
cd "${SCRIPT_DIR}" || exit 1
make clean
python3 -m pip uninstall -y shell-logger
cd ..
python3 -m pip install .
cd "${SCRIPT_DIR}" || exit 1
make html SPHINXOPTS="-W --keep-going"
cd "${ORIG_DIR}" || exit 1
