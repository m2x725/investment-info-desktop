import importlib.util
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location('release_source', Path(__file__).resolve().parents[1] / 'scripts' / 'Prepare-Release.py')
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


def test_export_excludes_account_and_local_artifacts(tmp_path):
    for name in ['backend/main.py', 'frontend/src/main.tsx', 'data/portfolio.db',
                 '.env', '.venv/private.py', 'docs/desktop-preview/window.png',
                 'backend/__pycache__/main.pyc', 'session.ses']:
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('test')
    files = [str(p.relative_to(tmp_path)) for p in release.release_files(tmp_path)]
    assert files == ['backend/main.py', 'frontend/src/main.tsx']


def test_detects_credential_without_printing_value(tmp_path, monkeypatch):
    monkeypatch.setattr(release, 'ROOT', tmp_path)
    p = tmp_path / 'bad.py'
    secret = 'sk-' + 'Q' * 30
    p.write_text(secret)
    with pytest.raises(RuntimeError) as exc:
        release.audit([p])
    assert 'bad.py' in str(exc.value)
    assert secret not in str(exc.value)
