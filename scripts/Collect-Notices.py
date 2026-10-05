"""Collect installed distributions' licence notices for release review/redistribution."""
import importlib.metadata,json
from pathlib import Path
root=Path('dist/third-party-notices');root.mkdir(parents=True,exist_ok=True)
manifest=[]
for distribution in importlib.metadata.distributions():
    metadata=distribution.metadata;name=metadata.get('Name','unknown');notices=[]
    for f in distribution.files or []:
        if Path(str(f)).name.lower().startswith(('license','licence','notice','copying','copyright')):
            source=distribution.locate_file(f)
            if not source.is_file() or source.stat().st_size>2000000:continue
            target=root/name/str(f).replace('..','_').replace(':','_').lstrip('/')
            target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(source.read_bytes());notices.append(str(target.relative_to(root)))
    manifest.append({'package':name,'version':distribution.version,'license':metadata.get('License-Expression') or metadata.get('License'),'notices':notices})
(root/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
print('Release licence manifest written; review packages with missing notices before publishing.')
