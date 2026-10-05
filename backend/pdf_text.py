"""Local extraction fallbacks, with OCR only for pages that fail readable-text checks."""
import io
from .research_engine import readable

def extract(blob):
    from pypdf import PdfReader
    reader=PdfReader(io.BytesIO(blob));pages=[];bad=[]
    for i,page in enumerate(reader.pages):
        try:text=page.extract_text() or ''
        except Exception:text='' 
        pages.append(text)
        if not readable(text):bad.append(i)
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
            engine=RapidOCR();doc=pdfium.PdfDocument(blob)
            try:
                # Preserve early business narrative and sample later financial tables within OCR work budget.
                selected=bad[:8]+[bad[round(j*(len(bad)-1)/11)] for j in range(12)] if len(bad)>20 else bad
                for i in sorted(set(selected)):
                    page=doc[i];bitmap=page.render(scale=1.5)
                    try:
                        result,_=engine(np.asarray(bitmap.to_pil()))
                        text='\n'.join(r[1] for r in result or [])
                        if readable(text):pages[i]=text
                    finally:bitmap.close();page.close()
            finally:doc.close()
        except ImportError:pass
        except Exception:pass
    return '\n'.join(f'[第{i+1}页]\n'+(text if readable(text) else '[此页文字不可读，未用作证据；待备用网页或OCR]') for i,text in enumerate(pages))
