"""Local extraction fallbacks, with OCR only for pages that fail readable-text checks."""
import io
from .research_engine import readable

def extract(blob, timeout=60):
    """A stalled native parser is killed rather than occupying the job pool forever."""
    import os
    import subprocess
    import sys
    import tempfile
    from pathlib import Path
    from .providers import ProviderError
    with tempfile.TemporaryDirectory(prefix='wealth-pdf-') as directory:
        source = Path(directory) / 'source.pdf'
        output = Path(directory) / 'text.txt'
        source.write_bytes(blob)
        command = ([sys.executable, '--pdf-worker'] if getattr(sys, 'frozen', False)
                   else [sys.executable, '-m', 'backend.pdf_worker'])
        env = {**os.environ, 'OMP_NUM_THREADS': '2', 'OPENBLAS_NUM_THREADS': '2', 'MKL_NUM_THREADS': '2'}
        options = {'creationflags': subprocess.CREATE_NO_WINDOW} if sys.platform == 'win32' else {}
        timed_out = False
        with subprocess.Popen(command + [str(source), str(output)], env=env,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **options) as process:
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                process.kill()
                process.wait()
        text = output.read_text(encoding='utf-8') if output.exists() else ''
        if timed_out and text:
            return text + '\n[PDF读取超时：已保留完成部分，其余页未读取，不作为证据]'
        if timed_out:
            raise ProviderError('PDF读取超时，保留来源链接并继续其他资料。')
        if process.returncode or not text.strip():
            raise ProviderError('PDF解析未完成，保留来源链接并继续其他资料。')
        return text


def _extract(blob, checkpoint=lambda text: None):
    from pypdf import PdfReader
    reader=PdfReader(io.BytesIO(blob));pages=[];bad=[]
    for i,page in enumerate(reader.pages):
        try:text=page.extract_text() or ''
        except Exception:text='' 
        pages.append(text)
        if not readable(text):bad.append(i)
        if i == 0 or i % 10 == 0:
            checkpoint('\n'.join(f'[第{j+1}页]\n'+(t if readable(t) else '[此页文字不可读，未用作证据]') for j,t in enumerate(pages)))
    checkpoint('\n'.join(f'[第{j+1}页]\n'+(t if readable(t) else '[此页文字不可读，未用作证据]') for j,t in enumerate(pages)))
    if bad:
        try:
            import pdfplumber
            with pdfplumber.open(io.BytesIO(blob)) as doc:
                for i in bad:
                    alternate=doc.pages[i].extract_text(layout=False) or ''
                    if readable(alternate):pages[i]=alternate
        except Exception:pass
    bad=[i for i,t in enumerate(pages) if not readable(t)]
    if bad:
        try:
            import pypdfium2 as pdfium
            from rapidocr_onnxruntime import RapidOCR
            import numpy as np
            engine=RapidOCR(intra_op_num_threads=2, inter_op_num_threads=1);doc=pdfium.PdfDocument(blob)
            try:
                # Preserve early business narrative and sample later financial tables within OCR work budget.
                selected=bad[:8]+[bad[round(j*(len(bad)-1)/11)] for j in range(12)] if len(bad)>20 else bad
                for i in sorted(set(selected)):
                    page=doc[i];bitmap=page.render(scale=1.5)
                    try:
                        result,_=engine(np.asarray(bitmap.to_pil()))
                        text='\n'.join(r[1] for r in result or [])
                        if readable(text):pages[i]=text
                        checkpoint('\n'.join(f'[第{j+1}页]\n'+(t if readable(t) else '[此页文字不可读，未用作证据]') for j,t in enumerate(pages)))
                    finally:bitmap.close();page.close()
            finally:doc.close()
        except ImportError:pass
        except Exception:pass
    return '\n'.join(f'[第{i+1}页]\n'+(text if readable(text) else '[此页文字不可读，未用作证据；待备用网页或OCR]') for i,text in enumerate(pages))
