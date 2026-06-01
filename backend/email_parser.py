"""邮件解析器 - 将邮件数据转换为可索引的文档"""

import os
from datetime import datetime


def email_to_text(email: dict) -> str:
    """将邮件转换为纯文本格式"""
    parts = []
    
    # 基本信息
    parts.append(f"主题: {email.get('subject', '无主题')}")
    parts.append(f"发件人: {email.get('sender_name', '')} <{email.get('sender', '')}>")
    parts.append(f"收件人: {email.get('recipients', '')}")
    
    if email.get('cc'):
        parts.append(f"抄送: {email['cc']}")
    
    parts.append(f"时间: {email.get('received_at', '')}")
    
    if email.get('has_attachments'):
        parts.append(f"附件: {email.get('attachment_names', '有附件')}")
    
    parts.append("")  # 空行分隔
    
    # 邮件正文
    body = email.get('body', '')
    if body:
        parts.append(body)
    
    return "\n".join(parts)


def email_to_chunks(email: dict, chunk_size: int = 500) -> list[dict]:
    """
    将单封邮件转换为多个文档块
    
    返回格式与 parser.py 的 process_file 一致
    """
    text = email_to_text(email)
    
    if not text.strip():
        return []
    
    # 分块
    chunks = []
    current_chunk = ""
    
    # 按段落分割
    paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]
    
    for para in paragraphs:
        if len(current_chunk) + len(para) <= chunk_size:
            current_chunk += ("\n\n" + para if current_chunk else para)
        else:
            if current_chunk:
                chunks.append(current_chunk)
            current_chunk = para
    
    if current_chunk:
        chunks.append(current_chunk)
    
    # 构造结果
    result = []
    filename = f"email_{email.get('id', 'unknown')}.eml"
    
    for i, chunk in enumerate(chunks):
        result.append({
            "filename": filename,
            "chunk_index": i,
            "content": chunk,
            "file_type": ".eml",
            # 邮件元数据
            "metadata": {
                "email_id": email.get('id'),
                "message_id": email.get('message_id'),
                "thread_id": email.get('thread_id'),
                "subject": email.get('subject'),
                "sender": email.get('sender'),
                "sender_name": email.get('sender_name'),
                "received_at": email.get('received_at'),
                "folder": email.get('folder'),
                "has_attachments": email.get('has_attachments', 0),
            }
        })
    
    return result


def batch_convert_emails(emails: list[dict], chunk_size: int = 500) -> list[dict]:
    """批量转换邮件为文档块"""
    all_chunks = []
    
    for email in emails:
        chunks = email_to_chunks(email, chunk_size)
        all_chunks.extend(chunks)
    
    return all_chunks


def format_email_for_display(email: dict) -> str:
    """格式化邮件用于展示"""
    lines = []
    lines.append(f"📧 {email.get('subject', '无主题')}")
    lines.append(f"   发件人: {email.get('sender_name', '')} <{email.get('sender', '')}>")
    lines.append(f"   时间: {email.get('received_at', '')[:19]}")
    
    if email.get('has_attachments'):
        lines.append(f"   📎 附件: {email.get('attachment_names', '')}")
    
    # 截断正文预览
    body = email.get('body', '')
    if body:
        preview = body[:100] + "..." if len(body) > 100 else body
        lines.append(f"   {preview}")
    
    return "\n".join(lines)
