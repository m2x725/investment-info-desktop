"""Isolate optional third-party financial network requests from the research pool."""
import json
import sys
from pathlib import Path


def main():
    from .data_adapters import _fetch_financial_history
    source, output=map(Path,sys.argv[-2:])
    security=json.loads(source.read_text(encoding='utf-8'))
    result=_fetch_financial_history(security)
    output.write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8')


if __name__ == '__main__':
    main()
