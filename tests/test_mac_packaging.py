from pathlib import Path
from backend import storage


def test_frozen_mac_uses_user_application_support(monkeypatch, tmp_path):
    monkeypatch.delenv('WEALTH_DATA_DIR', raising=False)
    monkeypatch.setattr(storage.sys, 'platform', 'darwin')
    monkeypatch.setattr(storage.sys, 'frozen', True, raising=False)
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    assert storage.default_data_dir() == tmp_path / 'Library' / 'Application Support' / 'InvestmentInfo'


def test_explicit_mac_data_directory_is_preserved(monkeypatch, tmp_path):
    monkeypatch.setenv('WEALTH_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(storage.sys, 'platform', 'darwin')
    monkeypatch.setattr(storage.sys, 'frozen', True, raising=False)
    assert storage.default_data_dir() == tmp_path
