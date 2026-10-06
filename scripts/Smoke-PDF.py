"""Verify the frozen PDF worker exits without opening an app or starting a server."""
import io
import subprocess
import sys
import tempfile
from pathlib import Path
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

writer=PdfWriter();page=writer.add_blank_page(width=600,height=800)
font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
content=DecodedStreamObject();content.set_data(b'BT /F1 12 Tf 30 700 Td (Revenue and operating profit improved during the financial year.) Tj ET')
page[NameObject('/Contents')]=writer._add_object(content)
with tempfile.TemporaryDirectory() as directory:
    source=Path(directory)/'sample.pdf';output=Path(directory)/'text.txt'
    writer.write(source)
    result=subprocess.run([str(Path(sys.argv[1]).resolve()),'--pdf-worker',str(source),str(output)],timeout=40)
    if result.returncode or not output.exists() or 'Revenue' not in output.read_text(encoding='utf-8'):
        raise SystemExit('Frozen PDF worker failed')
print('Frozen PDF worker smoke passed')
