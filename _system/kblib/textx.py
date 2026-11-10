# From 大大王.DT
"""文本提取：Office / PDF / 网页 / 图片说明 → 纯文本。"""
import re
import subprocess
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from .common import CODE_EXT, IMG_EXT, NOTE_SUFFIX, OFFICE_EXT, TEXT_EXT, html_text, read_text


def xml_texts(data, tag):
    return [t.text or '' for t in ET.fromstring(data).iter() if t.tag.endswith('}' + tag)]


def xlsx_text(p: Path):
    out = []
    with zipfile.ZipFile(p) as z:
        shared = []
        if 'xl/sharedStrings.xml' in z.namelist():
            for si in ET.fromstring(z.read('xl/sharedStrings.xml')):
                shared.append(''.join(t.text or '' for t in si.iter() if t.tag.endswith('}t')))
        sheets = sorted((n for n in z.namelist() if re.match(r'xl/worksheets/sheet\d+\.xml$', n)),
                        key=lambda n: int(re.findall(r'\d+', n)[-1]))
        for n in sheets:
            out.append(f'## {Path(n).stem}')
            for row in ET.fromstring(z.read(n)).iter():
                if not row.tag.endswith('}row'):
                    continue
                vals = []
                for c in row:
                    v = next((x.text for x in c.iter() if x.tag.endswith('}v')), None)
                    if c.get('t') == 's' and v is not None:
                        v = shared[int(v)]
                    elif c.get('t') == 'inlineStr':
                        v = ''.join(x.text or '' for x in c.iter() if x.tag.endswith('}t'))
                    vals.append(v or '')
                if any(vals):
                    out.append(' | '.join(vals))
    return '\n'.join(out)


def pptx_text(p: Path):
    out = []
    with zipfile.ZipFile(p) as z:
        slides = sorted((n for n in z.namelist() if re.match(r'ppt/slides/slide\d+\.xml$', n)),
                        key=lambda n: int(re.findall(r'\d+', n)[-1]))
        for i, n in enumerate(slides, 1):
            out.append(f'## 第 {i} 页\n' + '\n'.join(t for t in xml_texts(z.read(n), 't') if t.strip()))
    return '\n\n'.join(out)


def pdf_text(p: Path):
    try:
        from pypdf import PdfReader
    except ImportError:
        return f'[PDF 未解析：未安装 pypdf] {p.name}'
    pages = PdfReader(str(p)).pages
    return '\n\n'.join(f'## 第 {i} 页\n{pg.extract_text() or ""}' for i, pg in enumerate(pages, 1))


def extract(p: Path):
    ext = p.suffix.lower()
    try:
        if ext in IMG_EXT:
            note = p.with_name(p.name + NOTE_SUFFIX)
            return f'[图片] {p.name}' + ('（有说明）' if note.exists() else '（暂无说明）')
        if ext in ('.html', '.htm'):
            return html_text(read_text(p))
        if ext in OFFICE_EXT:
            return subprocess.run(['textutil', '-convert', 'txt', '-stdout', str(p)],
                                  capture_output=True, timeout=60).stdout.decode('utf-8', 'replace')
        if ext == '.pdf':
            return pdf_text(p)
        if ext == '.xlsx':
            return xlsx_text(p)
        if ext == '.pptx':
            return pptx_text(p)
        if ext in TEXT_EXT or ext in CODE_EXT:
            return read_text(p)
    except Exception as e:
        return f'[无法解析 {p.name}：{e}]'
    return None
