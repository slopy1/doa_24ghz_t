#!/usr/bin/env bash
#
# Workaround for gr-aoa binary modules built against older SONAMEs:
#   - libspdlog.so.1.11
#   - libfmt.so.9
#
# This script creates a tiny compat directory containing only the missing
# SONAMEs (symlinked from an existing conda install) and then executes the
# provided command with LD_LIBRARY_PATH pointing to that directory.
#
# Usage:
#   ./scripts/gr_aoa_compat_run.sh /usr/bin/python3 -u gnuradio_flowgraphs/aoa_estimation_bladerf.py
#   ./scripts/gr_aoa_compat_run.sh gnuradio-companion
#
set -euo pipefail

if [[ -z "${HOME:-}" ]]; then
  # Some launchers may provide a minimal environment; recover HOME.
  HOME="$(getent passwd "$(id -u)" | cut -d: -f6)"
  export HOME
fi

COMPAT_DIR="${HOME}/.local/gr_aoa_compat_libs"
CONDA_LIB="${HOME}/miniconda3/lib"

SPDLOG_SRC="${CONDA_LIB}/libspdlog.so.1.11.0"
FMT_SRC="${CONDA_LIB}/libfmt.so.9.1.0"

mkdir -p "${COMPAT_DIR}"

if [[ ! -f "${SPDLOG_SRC}" ]]; then
  echo "gr-aoa compat error: missing ${SPDLOG_SRC}" >&2
  echo "Expected a conda base install at ${CONDA_LIB} containing spdlog 1.11.x" >&2
  exit 1
fi

if [[ ! -f "${FMT_SRC}" ]]; then
  echo "gr-aoa compat error: missing ${FMT_SRC}" >&2
  echo "Expected a conda base install at ${CONDA_LIB} containing fmt 9.x" >&2
  exit 1
fi

ln -sf "${SPDLOG_SRC}" "${COMPAT_DIR}/libspdlog.so.1.11"
ln -sf "${FMT_SRC}" "${COMPAT_DIR}/libfmt.so.9"

export LD_LIBRARY_PATH="${COMPAT_DIR}${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"

# Force system libstdc++ to prevent miniconda's older version from being used
# (miniconda's version lacks GLIBCXX_3.4.32 required by the AOA C++ extension)
export LD_PRELOAD="/usr/lib/libstdc++.so.6"

# Prioritize Python 3.14's site-packages where the rebuilt gr-aoa module is installed
export PYTHONPATH="/usr/local/lib/python3.14/site-packages${PYTHONPATH:+:${PYTHONPATH}}"

exec "$@"


