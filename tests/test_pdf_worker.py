import io
import subprocess
import pytest
from backend.pdf_text import extract
from backend.providers import ProviderError


def test_worker_reads_real_pdf():
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
    writer=PdfWriter(); page=writer.add_blank_page(width=600,height=800)
    font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
    page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
    content=DecodedStreamObject(); content.set_data(b'BT /F1 12 Tf 30 700 Td (Revenue and operating profit improved during the financial year.) Tj ET')
    page[NameObject('/Contents')]=writer._add_object(content)
    stream=io.BytesIO(); writer.write(stream)
    assert 'Revenue' in extract(stream.getvalue(), timeout=20)


def test_timeout_kills_worker_and_keeps_checkpoint(monkeypatch):
    class Hung:
        returncode=None
        def __init__(self,command,**kwargs):
            from pathlib import Path
            Path(command[-1]).write_text('[第1页]\n已经读取的原文',encoding='utf-8')
            self.killed=False
        def __enter__(self):return self
        def __exit__(self,*args):assert self.killed
        def wait(self,timeout=None):
            if timeout is not None:raise subprocess.TimeoutExpired('worker',timeout)
            self.returncode=-9
        def kill(self):self.killed=True
    monkeypatch.setattr(subprocess,'Popen',Hung)
    result=extract(b'%PDF-test',timeout=.01)
    assert '已经读取的原文' in result and '其余页未读取' in result


def test_unreadable_pdf_fails_without_starting_app():
    with pytest.raises(ProviderError,match='PDF解析未完成'):
        extract(b'%PDF-invalid',timeout=20)
