#!/usr/bin/env bash
# Hackathon setup for Linux: installs uv, Python 3.12 and the dependencies into ./.venv (no sudo needed)
# Run:  bash setup_linux.sh
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v uv >/dev/null 2>&1; then
    echo "Installing uv (Python installer)..."
    if command -v curl >/dev/null 2>&1; then
        curl -LsSf https://astral.sh/uv/install.sh | sh
    elif command -v wget >/dev/null 2>&1; then
        wget -qO- https://astral.sh/uv/install.sh | sh
    else
        echo "Please install curl or wget first (e.g. sudo apt install curl)" >&2
        exit 1
    fi
    export PATH="$HOME/.local/bin:$PATH"
fi

echo "Creating .venv with Python 3.12..."
uv venv --python 3.12 --allow-existing .venv
uv pip install --python .venv -r requirements.txt

echo "Checking..."
.venv/bin/python -c "import requests, sseclient, pandas, models, base_bot; print('All good:', __import__('sys').version.split()[0])"

echo
echo "Done. Start each new terminal with:   source .venv/bin/activate"
echo "Then run e.g.:                       python energi_snippet.py"
