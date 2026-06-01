"""邮件数据库模拟 - SQLite 存储邮件数据"""

import sqlite3
import os
from datetime import datetime, timedelta
import random

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "emails.db")


def get_connection():
    """获取数据库连接"""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """初始化邮件数据库"""
    conn = get_connection()
    cursor = conn.cursor()
    
    # 创建邮件表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS emails (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id TEXT UNIQUE,
            thread_id TEXT,
            subject TEXT,
            sender TEXT,
            sender_name TEXT,
            recipients TEXT,
            cc TEXT,
            body TEXT,
            html_body TEXT,
            has_attachments INTEGER DEFAULT 0,
            attachment_names TEXT,
            received_at TEXT,
            folder TEXT DEFAULT 'INBOX',
            is_read INTEGER DEFAULT 0,
            labels TEXT
        )
    ''')
    
    # 创建索引
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_thread ON emails(thread_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_sender ON emails(sender)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_received ON emails(received_at)')
    
    conn.commit()
    conn.close()


def insert_email(email: dict):
    """插入单封邮件"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT OR IGNORE INTO emails 
        (message_id, thread_id, subject, sender, sender_name, recipients, cc, 
         body, html_body, has_attachments, attachment_names, received_at, folder, is_read, labels)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        email.get('message_id'),
        email.get('thread_id'),
        email.get('subject'),
        email.get('sender'),
        email.get('sender_name'),
        email.get('recipients'),
        email.get('cc'),
        email.get('body'),
        email.get('html_body'),
        email.get('has_attachments', 0),
        email.get('attachment_names'),
        email.get('received_at'),
        email.get('folder', 'INBOX'),
        email.get('is_read', 0),
        email.get('labels')
    ))
    
    conn.commit()
    conn.close()


def batch_insert_emails(emails: list[dict]):
    """批量插入邮件"""
    conn = get_connection()
    cursor = conn.cursor()
    
    for email in emails:
        cursor.execute('''
            INSERT OR IGNORE INTO emails 
            (message_id, thread_id, subject, sender, sender_name, recipients, cc, 
             body, html_body, has_attachments, attachment_names, received_at, folder, is_read, labels)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            email.get('message_id'),
            email.get('thread_id'),
            email.get('subject'),
            email.get('sender'),
            email.get('sender_name'),
            email.get('recipients'),
            email.get('cc'),
            email.get('body'),
            email.get('html_body'),
            email.get('has_attachments', 0),
            email.get('attachment_names'),
            email.get('received_at'),
            email.get('folder', 'INBOX'),
            email.get('is_read', 0),
            email.get('labels')
        ))
    
    conn.commit()
    conn.close()


def get_all_emails(folder: str = None, limit: int = 1000) -> list[dict]:
    """获取所有邮件"""
    conn = get_connection()
    cursor = conn.cursor()
    
    if folder:
        cursor.execute('SELECT * FROM emails WHERE folder = ? ORDER BY received_at DESC LIMIT ?', (folder, limit))
    else:
        cursor.execute('SELECT * FROM emails ORDER BY received_at DESC LIMIT ?', (limit,))
    
    rows = cursor.fetchall()
    conn.close()
    
    return [dict(row) for row in rows]


def get_email_by_id(email_id: int) -> dict:
    """根据ID获取邮件"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM emails WHERE id = ?', (email_id,))
    row = cursor.fetchone()
    conn.close()
    
    return dict(row) if row else None


def get_thread_emails(thread_id: str) -> list[dict]:
    """获取邮件线程"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM emails WHERE thread_id = ? ORDER BY received_at ASC', (thread_id,))
    rows = cursor.fetchall()
    conn.close()
    
    return [dict(row) for row in rows]


def search_emails(query: str, limit: int = 50) -> list[dict]:
    """搜索邮件（关键词）"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT * FROM emails 
        WHERE subject LIKE ? OR body LIKE ? OR sender_name LIKE ?
        ORDER BY received_at DESC LIMIT ?
    ''', (f'%{query}%', f'%{query}%', f'%{query}%', limit))
    
    rows = cursor.fetchall()
    conn.close()
    
    return [dict(row) for row in rows]


def get_folders() -> list[str]:
    """获取所有文件夹"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('SELECT DISTINCT folder FROM emails')
    rows = cursor.fetchall()
    conn.close()
    
    return [row['folder'] for row in rows]


def get_stats() -> dict:
    """获取邮件统计"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('SELECT COUNT(*) as total FROM emails')
    total = cursor.fetchone()['total']
    
    cursor.execute('SELECT COUNT(DISTINCT thread_id) as threads FROM emails')
    threads = cursor.fetchone()['threads']
    
    cursor.execute('SELECT COUNT(DISTINCT sender) as senders FROM emails')
    senders = cursor.fetchone()['senders']
    
    cursor.execute('SELECT folder, COUNT(*) as count FROM emails GROUP BY folder')
    folders = {row['folder']: row['count'] for row in cursor.fetchall()}
    
    conn.close()
    
    return {
        'total_emails': total,
        'total_threads': threads,
        'total_senders': senders,
        'folders': folders
    }


def generate_sample_emails(count: int = 50) -> list[dict]:
    """生成模拟邮件数据"""
    
    # 模拟发件人
    senders = [
        ("zhangsan@company.com", "张三"),
        ("lisi@company.com", "李四"),
        ("wangwu@company.com", "王五"),
        ("zhaoliu@company.com", "赵六"),
        ("sunqi@company.com", "孙七"),
        ("hr@company.com", "人力资源部"),
        ("tech@company.com", "技术部"),
        ("product@company.com", "产品部"),
    ]
    
    # 模拟主题
    subjects = [
        "关于项目进度的讨论",
        "本周工作总结",
        "会议纪要：产品评审会",
        "需求文档更新通知",
        "代码审查反馈",
        "请假申请",
        "报销单审批",
        "新员工入职欢迎",
        "技术分享：微服务架构",
        "Q3季度目标确认",
        "客户反馈处理",
        "系统上线通知",
        "安全漏洞修复",
        "团队建设活动通知",
        "年终奖发放说明",
    ]
    
    # 模拟邮件内容
    bodies = [
        """各位同事：

关于XX项目的进度，目前前端开发已完成80%，后端接口开发完成60%。
预计下周三可以完成联调，周五提交测试。

请各位抓紧时间，有问题及时沟通。

Best regards,
张三""",
        
        """本周工作总结：

1. 完成用户模块开发
2. 修复了3个线上bug
3. 参加产品评审会议
4. 编写技术文档

下周计划：
1. 开始订单模块开发
2. 优化数据库查询性能""",
        
        """会议纪要 - 产品评审会

时间：2024年5月20日 14:00-16:00
参会人员：产品部、技术部、设计部

主要议题：
1. 新功能需求评审
2. 用户反馈分析
3. 下版本迭代计划

决议：
- 优先开发搜索优化功能
- 增加数据导出功能
- 优化移动端体验""",
        
        """需求文档已更新，请查看附件。

主要变更：
1. 新增批量操作功能
2. 优化筛选条件
3. 增加数据校验规则

请各位开发同学review，有问题及时反馈。

产品部""",
        
        """代码审查反馈：

PR #123 - 用户登录模块

问题：
1. 密码加密方式建议使用bcrypt
2. 缺少输入参数校验
3. 日志记录不完整

建议修改后重新提交。

技术部""",
    ]
    
    emails = []
    base_time = datetime.now() - timedelta(days=30)
    
    for i in range(count):
        sender_email, sender_name = random.choice(senders)
        subject = random.choice(subjects)
        body = random.choice(bodies)
        thread_id = f"thread_{i // 3}"  # 每3封邮件一个线程
        
        email = {
            'message_id': f"msg_{i}_{random.randint(1000, 9999)}",
            'thread_id': thread_id,
            'subject': subject,
            'sender': sender_email,
            'sender_name': sender_name,
            'recipients': "team@company.com",
            'cc': "",
            'body': body,
            'html_body': f"<p>{body}</p>",
            'has_attachments': random.choice([0, 0, 0, 1]),
            'attachment_names': "document.pdf" if random.random() > 0.7 else "",
            'received_at': (base_time + timedelta(hours=random.randint(0, 720))).isoformat(),
            'folder': random.choice(['INBOX', 'INBOX', 'INBOX', 'Sent', 'Drafts']),
            'is_read': random.choice([0, 1]),
            'labels': random.choice(['', '重要', '工作', '个人'])
        }
        emails.append(email)
    
    return emails


def init_sample_data():
    """初始化示例数据"""
    init_db()
    
    # 检查是否已有数据
    stats = get_stats()
    if stats['total_emails'] > 0:
        print(f"数据库已有 {stats['total_emails']} 封邮件，跳过初始化")
        return
    
    # 生成并插入示例邮件
    emails = generate_sample_emails(50)
    batch_insert_emails(emails)
    print(f"已生成 {len(emails)} 封示例邮件")


if __name__ == "__main__":
    init_sample_data()
    print(get_stats())
