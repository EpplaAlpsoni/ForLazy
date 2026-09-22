#!/usr/bin/env bash
set -euo pipefail
script_path="$(readlink -f -- "${BASH_SOURCE[0]}")"
cd -- "$(dirname -- "$script_path")"

# Everything downloaded stays here, including Python and uv's cache.
export UV_CACHE_DIR="$PWD/.tools/cache"
export UV_PYTHON_INSTALL_DIR="$PWD/.tools/python"
if [[ ! -x .tools/bin/uv ]]; then
    mkdir -p .tools/bin
    echo 'Downloading uv into .tools (first launch only)…'
    curl --fail --location --proto '=https' --tlsv1.2 \
        https://astral.sh/uv/install.sh -o .tools/uv-install.sh
    UV_UNMANAGED_INSTALL="$PWD/.tools/bin" sh .tools/uv-install.sh
fi
if [[ ! -x .venv/bin/python ]]; then
    .tools/bin/uv venv --python 3.12 --managed-python .venv
fi
if ! cmp -s requirements.txt .venv/forlazy-requirements.txt; then
    .tools/bin/uv pip install --python .venv/bin/python -r requirements.txt
    cp requirements.txt .venv/forlazy-requirements.txt
fi
if [[ "${1:-}" == --install-only ]]; then
    echo 'ForLazy is installed. Run ./run.sh to launch.'
    exit 0
fi
exec .venv/bin/python main.py "$@"
