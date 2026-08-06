#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
pyinstaller --noconfirm --clean GrantReviewAssistant.spec
echo "Build finished. Open dist/基金评审助手.app"
