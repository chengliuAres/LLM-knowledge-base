"""文档解析器 - 支持 PDF/TXT/MD/DOCX/EML"""

import os
import re
from pathlib import Path


def read_file(file_path: str) -> str:
    """读取文件内容，根据扩展名选择解析方式"""
    ext = Path(file_path).suffix.lower()
    
    if ext == '.pdf':
        return read_pdf(file_path)
    elif ext in ('.txt', '.md'):
        return read_text(file_path)
    elif ext == '.docx':
        return read_docx(file_path)
    elif ext == '.eml':
        text, _ = read_eml(file_path)
        return text
    else:
        raise ValueError(f"不支持的文件格式: {ext}")


def read_pdf(file_path: str) -> str:
    """读取 PDF 文件"""
    from PyPDF2 import PdfReader
    
    reader = PdfReader(file_path)
    text_parts = []
    
    for page in reader.pages:
        page_text = page.extract_text()
        if page_text:
            text_parts.append(page_text.strip())
    
    return "\n\n".join(text_parts)


def read_text(file_path: str) -> str:
    """读取纯文本/Markdown 文件"""
    with open(file_path, 'r', encoding='utf-8') as f:
        return f.read()


def read_docx(file_path: str) -> str:
    """读取 Word 文档"""
    from docx import Document
    
    doc = Document(file_path)
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    return "\n\n".join(paragraphs)


def read_eml(file_path: str) -> tuple[str, dict]:
    """解析 .eml 邮件文件，返回 (拼装后的纯文本, metadata 字典)"""
    import email
    from email.header import decode_header
    from email.utils import parsedate_to_datetime

    def _decode_header(value: str) -> str:
        if not value:
            return ''
        parts = []
        for chunk, enc in decode_header(value):
            if isinstance(chunk, bytes):
                chunk = chunk.decode(enc or 'utf-8', errors='replace')
            parts.append(chunk)
        return ''.join(parts)

    with open(file_path, 'rb') as f:
        msg = email.message_from_binary_file(f)

    subject = _decode_header(msg.get('Subject', ''))
    sender_raw = _decode_header(msg.get('From', ''))
    to = _decode_header(msg.get('To', ''))
    cc = _decode_header(msg.get('Cc', ''))
    date_raw = msg.get('Date', '')
    received_at = ''
    if date_raw:
        try:
            received_at = parsedate_to_datetime(date_raw).isoformat()
        except (TypeError, ValueError):
            received_at = date_raw

    body_parts: list[str] = []
    attachments: list[str] = []
    for part in msg.walk() if msg.is_multipart() else [msg]:
        ctype = part.get_content_type()
        disp = (part.get('Content-Disposition') or '').lower()
        if 'attachment' in disp:
            fn = _decode_header(part.get_filename() or '')
            if fn:
                attachments.append(fn)
            continue
        if ctype == 'text/plain':
            payload = part.get_payload(decode=True)
            if payload:
                charset = part.get_content_charset() or 'utf-8'
                try:
                    body_parts.append(payload.decode(charset, errors='replace'))
                except (LookupError, UnicodeDecodeError):
                    body_parts.append(payload.decode('utf-8', errors='replace'))
    body = '\n\n'.join(p.strip() for p in body_parts if p.strip())

    text_parts = [
        f"主题: {subject or '(无主题)'}",
        f"发件人: {sender_raw or '(未知)'}",
    ]
    if to:
        text_parts.append(f"收件人: {to}")
    if cc:
        text_parts.append(f"抄送: {cc}")
    if received_at:
        text_parts.append(f"时间: {received_at}")
    if attachments:
        text_parts.append(f"附件: {', '.join(attachments)}")
    text_parts.append('')
    if body:
        text_parts.append(body)
    text = '\n'.join(text_parts)

    addr_match = re.search(r'<([^>]+)>', sender_raw)
    sender_addr = addr_match.group(1).strip() if addr_match else sender_raw.strip()
    name_match = re.match(r'\s*"?([^"<]+?)"?\s*<', sender_raw)
    sender_name = name_match.group(1).strip() if name_match else ''

    metadata = {
        'subject': subject,
        'sender': sender_addr,
        'sender_name': sender_name,
        'recipients': to,
        'cc': cc,
        'received_at': received_at,
        'has_attachments': 1 if attachments else 0,
        'attachment_names': ', '.join(attachments),
        'source': 'uploaded_eml',
    }
    return text, metadata


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
    """
    将文本分块
    
    策略: 按段落优先，段落过长则按句子切分，保持语义完整性
    """
    # 先按段落分割
    paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]
    
    chunks = []
    current_chunk = ""
    
    for para in paragraphs:
        # 如果当前块加上新段落不超过限制，合并
        if len(current_chunk) + len(para) <= chunk_size:
            current_chunk += ("\n\n" + para if current_chunk else para)
        else:
            # 保存当前块
            if current_chunk:
                chunks.append(current_chunk)
            
            # 段落本身超过限制，需要进一步切分
            if len(para) > chunk_size:
                sub_chunks = split_long_text(para, chunk_size, overlap)
                chunks.extend(sub_chunks)
                current_chunk = ""
            else:
                current_chunk = para
    
    # 最后一个块
    if current_chunk:
        chunks.append(current_chunk)
    
    return chunks


def split_long_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    """对长文本按句子切分，带重叠"""
    import re
    
    # 按句子分割（中英文标点）
    sentences = re.split(r'([。！？.!?\n])', text)
    
    # 重新组合句子（把标点加回去）
    merged_sentences = []
    for i in range(0, len(sentences) - 1, 2):
        merged_sentences.append(sentences[i] + (sentences[i + 1] if i + 1 < len(sentences) else ''))
    
    if len(sentences) % 2 == 1 and sentences[-1]:
        merged_sentences.append(sentences[-1])
    
    chunks = []
    current_chunk = ""
    
    for sent in merged_sentences:
        if len(current_chunk) + len(sent) <= chunk_size:
            current_chunk += sent
        else:
            if current_chunk:
                chunks.append(current_chunk)
            current_chunk = sent
    
    if current_chunk:
        chunks.append(current_chunk)
    
    return chunks if chunks else [text[:chunk_size]]


def process_file(file_path: str, chunk_size: int = 500) -> list[dict]:
    """
    处理单个文件：读取 → 分块 → 返回结构化数据

    .eml 文件除了正文还会附带 metadata（subject/sender/收件人/时间等）
    """
    filename = os.path.basename(file_path)
    ext = Path(file_path).suffix.lower()

    metadata: dict = {}
    if ext == '.eml':
        content, metadata = read_eml(file_path)
    else:
        content = read_file(file_path)

    if not content.strip():
        return []

    chunks = chunk_text(content, chunk_size=chunk_size)

    result = []
    for i, chunk in enumerate(chunks):
        record = {
            "filename": filename,
            "chunk_index": i,
            "content": chunk,
            "file_type": ext,
        }
        if metadata:
            record["metadata"] = metadata
        result.append(record)
    
    return result
