"""Disposable local PDF process; never starts the application or calls cloud services."""
import sys
from pathlib import Path


def main():
    from .pdf_text import _extract
    source, output = map(Path, sys.argv[-2:])
    def checkpoint(text):
        temporary = output.with_suffix('.pending')
        temporary.write_text(text, encoding='utf-8')
        temporary.replace(output)
    checkpoint(_extract(source.read_bytes(), checkpoint=checkpoint))


if __name__ == '__main__':
    main()
