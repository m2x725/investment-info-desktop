#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
PYTHON="${WEALTH_BUILD_PYTHON:-.venv/bin/python}"
export PYINSTALLER_CONFIG_DIR="${PYINSTALLER_CONFIG_DIR:-$PWD/build/pyinstaller-cache}"
test -f frontend/dist/index.html
"$PYTHON" -m PyInstaller --noconfirm --clean --onedir --windowed --name InvestmentInfo --osx-bundle-identifier com.investmentinfo.desktop --add-data 'frontend/dist:frontend/dist' --collect-all webview --hidden-import webview.platforms.cocoa --collect-all openpyxl --collect-all pdfplumber --collect-all pypdfium2 --collect-all rapidocr_onnxruntime --collect-all onnxruntime --collect-all akshare --collect-all riskfolio --collect-all futu --collect-all cvxpy --collect-all clarabel --collect-all scipy --collect-all statsmodels --copy-metadata riskfolio-lib --copy-metadata akshare run.py
"$PYTHON" scripts/Collect-Notices.py
cp -R dist/third-party-notices dist/InvestmentInfo.app/Contents/Resources/
# Finder can restore bundle metadata in Documents while signing. Stage a clean copy outside it.
MAC_STAGE_DIR="$(mktemp -d /private/tmp/investment-mac-stage.XXXXXX)"
/usr/bin/ditto --norsrc --noextattr --noacl dist/InvestmentInfo.app "$MAC_STAGE_DIR/InvestmentInfo.app"
xattr -cr "$MAC_STAGE_DIR/InvestmentInfo.app"
codesign --force --deep --sign - "$MAC_STAGE_DIR/InvestmentInfo.app"
codesign --verify --deep --strict "$MAC_STAGE_DIR/InvestmentInfo.app"
/usr/bin/ditto -c -k --sequesterRsrc --keepParent "$MAC_STAGE_DIR/InvestmentInfo.app" dist/InvestmentInfo-macOS-arm64.zip
shasum -a 256 dist/InvestmentInfo-macOS-arm64.zip > dist/SHA256SUMS-macOS.txt
