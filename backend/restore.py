"""Offline verified SQLite restoration; never modify a live application database."""
import os,socket,sqlite3,uuid
from pathlib import Path
from contextlib import closing
from datetime import datetime

def restore(backup,directory,check_running=True):
    backup=Path(backup).resolve();directory=Path(directory).resolve();directory.mkdir(parents=True,exist_ok=True)
    target=directory/'portfolio.db'
    if backup==target:raise ValueError('备份不能是当前数据库')
    if check_running:
        with socket.socket() as probe:
            if probe.connect_ex(('127.0.0.1',8765))==0:raise ValueError('请先从托盘退出软件，再恢复备份')
    if not backup.is_file():raise ValueError('备份文件不存在')
    staged=directory/('restore-'+uuid.uuid4().hex+'.db')
    try:
        with closing(sqlite3.connect(backup.as_uri()+'?mode=ro',uri=True)) as source:
            if source.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('备份完整性检查失败')
            tables={r[0] for r in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not {'securities','positions','cash','reports','settings'}.issubset(tables):raise ValueError('不是本软件的数据库备份')
            with closing(sqlite3.connect(staged)) as destination:source.backup(destination)
        preserved=None
        if target.exists():
            folder=directory/'backups';folder.mkdir(exist_ok=True)
            preserved=folder/('before-restore-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6]+'.db')
            with closing(sqlite3.connect(target)) as source,closing(sqlite3.connect(preserved)) as dest:source.backup(dest)
        # Old WAL files must not be replayed into the restored database; application is stopped.
        for suffix in ('-wal','-shm'):
            sidecar=Path(str(target)+suffix)
            if sidecar.exists():sidecar.unlink()
        os.replace(staged,target)
        return {'restored':str(target),'previous_backup':str(preserved) if preserved else None}
    finally:
        if staged.exists():staged.unlink()
