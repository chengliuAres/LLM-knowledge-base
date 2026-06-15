"""Skill 接入子页 — 后端 API (FastAPI router)"""
import ast
import io
import os
import zipfile

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

router = APIRouter()

# export/code-search/ 是项目根的相对路径（main.py 启动时 cwd = backend/，所以是 ../export/code-search）
EXPORT_DIR = os.path.join(os.path.dirname(__file__), "..", "export", "code-search")


def _list_export_files() -> list:
    """列出 export/code-search/ 下所有文件 + 大小（相对 EXPORT_DIR）"""
    if not os.path.isdir(EXPORT_DIR):
        return []
    out = []
    for root, _, files in os.walk(EXPORT_DIR):
        for f in files:
            full = os.path.join(root, f)
            rel = os.path.relpath(full, EXPORT_DIR)
            out.append({"name": rel, "size": os.path.getsize(full)})
    return out


@router.get("/api/skill/raw")
def get_skill_raw():
    """返回 SKILL.md 文本 + 元信息"""
    path = os.path.join(EXPORT_DIR, "SKILL.md")
    if not os.path.exists(path):
        raise HTTPException(status_code=500, detail={"error": "SKILL.md missing", "path": path})
    content = open(path, encoding="utf-8").read()
    return {
        "content": content,
        "size": len(content),
        "files": _list_export_files(),
    }


@router.get("/api/skill/info")
def get_skill_info():
    """zip 元信息：大小、文件数、清单"""
    files = _list_export_files()
    total_size = sum(f["size"] for f in files)
    return {"file_count": len(files), "total_size": total_size, "files": files}


@router.get("/api/skill/download")
def download_skill():
    """打包 export/code-search/ 为 zip，根目录重命名 code-search/"""
    if not os.path.isdir(EXPORT_DIR):
        raise HTTPException(status_code=500, detail={"error": f"{EXPORT_DIR} not found"})

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(EXPORT_DIR):
            for f in files:
                src = os.path.join(root, f)
                arc = os.path.join("code-search", os.path.relpath(src, EXPORT_DIR))
                zf.write(src, arc)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="code-search.zip"'},
    )


def _parse_kb_api_commands() -> list:
    """用 ast 解析 kb_rest.py 的 argparse subparsers/add_parser 节点

    匹配模式: subparsers.add_parser("xxx", help="yyy")
    返回: [{"name": "xxx", "help": "yyy"}, ...]
    """
    py_path = os.path.join(EXPORT_DIR, "scripts", "kb_rest.py")
    if not os.path.exists(py_path):
        return []
    try:
        source = open(py_path, encoding="utf-8").read()
        tree = ast.parse(source)
    except SyntaxError:
        return []
    commands = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            # 匹配: <obj>.add_parser(<Constant "xxx">, ...)
            if (isinstance(node.func, ast.Attribute)
                    and node.func.attr == "add_parser"
                    and node.args and isinstance(node.args[0], ast.Constant)):
                name = node.args[0].value
                help_text = ""
                for kw in node.keywords:
                    if kw.arg == "help" and isinstance(kw.value, ast.Constant):
                        help_text = kw.value.value
                commands.append({"name": name, "help": help_text})
    return commands


@router.get("/api/skill/commands")
def get_skill_commands():
    """解析 kb_rest.py 的 argparse subcommands，返回 [{name, help}]"""
    return {"commands": _parse_kb_api_commands()}
