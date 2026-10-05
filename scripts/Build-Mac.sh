#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
PYTHON="${WEALTH_BUILD_PYTHON:-.venv/bin/python}"
test -f frontend/dist/index.html
"$PYTHON" -m PyInstaller --noconfirm --clean --onedir --windowed --name InvestmentInfo --osx-bundle-identifier com.investmentinfo.desktop --add-data 'frontend/dist:frontend/dist' --collect-all webview --hidden-import webview.platforms.cocoa --collect-all openpyxl --collect-all pdfplumber --collect-all pypdfium2 --collect-all rapidocr_onnxruntime --collect-all onnxruntime --collect-all akshare --collect-all riskfolio --collect-all futu --collect-all cvxpy --collect-all clarabel --collect-all scipy --collect-all statsmodels --copy-metadata riskfolio-lib --copy-metadata akshare run.py
"$PYTHON" scripts/Collect-Notices.py
cp -R dist/third-party-notices dist/InvestmentInfo.app/Contents/Resources/
codesign --force --deep --sign - dist/InvestmentInfo.app
/usr/bin/ditto -c -k --sequesterRsrc --keepParent dist/InvestmentInfo.app dist/InvestmentInfo-macOS-arm64.zip
shasum -a 256 dist/InvestmentInfo-macOS-arm64.zip > dist/SHA256SUMS-macOS.txt
