"""Export an allowlisted source tree; never export account data or local history."""
import argparse
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIRS = ('backend', 'frontend/src', 'frontend/public', 'scripts', 'tests', 'packaging', '.github/workflows')
FILES = ('run.py', 'Start.bat', 'requirements.txt', 'requirements-analysis.txt',
         'requirements-desktop.txt', 'requirements-windows.txt', 'requirements-dev.txt',
         'frontend/index.html', 'frontend/demo.html', 'frontend/research-demo.html',
         'frontend/package.json', 'frontend/package-lock.json', 'frontend/tsconfig.json',
         'frontend/vite.config.ts', 'docs/OPEN_SOURCE_REVIEW.md', 'docs/RELEASE_NOTES.md',
         'docs/WINDOWS_INSTALL.md', 'docs/PUBLIC_README.md', '.gitignore')
PATTERNS = [re.compile(r'sk-[A-Za-z0-9_-]{20,}'), re.compile(r'SCT\d+[A-Za-z0-9]{16,}'),
            re.compile(r'gh[pousr]_[A-Za-z0-9]{20,}'), re.compile(r'github_pat_[A-Za-z0-9_]{20,}')]

def release_files(root=ROOT):
    result = [root / name for name in FILES if (root / name).is_file()]
    for name in DIRS:
        directory = root / name
        if directory.exists():
            result += [p for p in directory.rglob('*') if p.is_file()
                       and '__pycache__' not in p.parts and p.suffix not in ('.pyc', '.db', '.sqlite', '.log')]
    return sorted(set(result))

def audit(paths):
    issues = []
    for path in paths:
        text = path.read_text(encoding='utf-8', errors='ignore')
        if any(pattern.search(text) for pattern in PATTERNS):
            issues.append(str(path.relative_to(ROOT)))
    if issues:
        raise RuntimeError('Possible credentials detected; file names only: ' + ', '.join(issues))

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    paths = release_files()
    audit(paths)
    if args.output:
        output = args.output.resolve()
        if output.exists():
            raise SystemExit('Choose a new empty output directory; existing files will not be overwritten.')
        output.mkdir(parents=True)
        for path in paths:
            target = output / path.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
        shutil.copy2(ROOT / 'docs/PUBLIC_README.md', output / 'README.md')
    print(f'Release allowlist checked: {len(paths)} files; no credential patterns detected. Manual review remains necessary.')
