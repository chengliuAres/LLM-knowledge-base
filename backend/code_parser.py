"""代码解析器 - tree-sitter AST 解析 + 混合分块

支持语言: ObjC, Swift, Java, Kotlin, Dart, C/C++/ObjC++
"""

import os
import re
from pathlib import Path
from typing import Optional

from code_skip_rules import get_skip_dirs, get_skip_exts

# ── 注释剥离（embedding 前清洗，避免中文注释/字符串干扰跨语言检索）──
# C 系语言: // 单行 + /* */ 多行
_C_COMMENT_RE = re.compile(r'//[^\n]*|/\*[\s\S]*?\*/')
# Python/Ruby/Shell/YAML: # 单行注释
_HASH_COMMENT_RE = re.compile(r'#[^\n]*')
# 中文字符连续串：代码中几乎是噪声（注释已被剥离，剩余多为硬编码字符串/测试数据）
# 剥离后避免跨语言 embedding 模型被中文 query 匹配到代码里的中文字面量
_CN_STRIP_RE = re.compile(r'[一-鿿㐀-䶿\U00020000-\U0002a6df]+')

# ── tree-sitter Parser 全局缓存 ─────────────────────────────────────
# tree_sitter_language_pack 的 get_parser() 每次创建全新的 Language+Parser
# 不缓存会导致 3773 个文件 = 3773 个 Language(含完整语法) + 3773 个 Parser → 内存爆炸
_PARSER_CACHE = {}

def _get_cached_parser(language: str):
    """获取缓存的 tree-sitter Parser（每种语言只创建一个，复用）"""
    if language not in _PARSER_CACHE:
        from tree_sitter_language_pack import get_parser
        _PARSER_CACHE[language] = get_parser(language)
    return _PARSER_CACHE[language]

# ── 语言 ↔ 扩展名映射 ──────────────────────────────────────────────

EXTENSION_MAP = {
    # ObjC / Swift
    '.m': 'objc',
    '.h': 'objc',
    '.swift': 'swift',
    # Java / Kotlin
    '.java': 'java',
    '.kt': 'kotlin',
    '.kts': 'kotlin',
    # Dart
    '.dart': 'dart',
    # C / C++ / ObjC++
    '.cpp': 'cpp',
    '.cc': 'cpp',
    '.cxx': 'cpp',
    '.c': 'cpp',
    '.hpp': 'cpp',
    '.hxx': 'cpp',
    '.mm': 'cpp',  # ObjC++ 用 cpp parser
    # Python
    '.py': 'python',
    '.pyi': 'python',
    # Ruby
    '.rb': 'ruby',
    # JavaScript / TypeScript
    '.js': 'javascript',
    '.jsx': 'javascript',
    '.ts': 'typescript',
    '.tsx': 'typescript',
    # Go
    '.go': 'go',
    # Rust
    '.rs': 'rust',
    # Shell
    '.sh': 'shell',
    '.bash': 'shell',
    '.zsh': 'shell',
    # YAML
    '.yml': 'yaml',
    '.yaml': 'yaml',
    # JSON
    '.json': 'json',
}

# ── AST 节点类型 → chunk_type 映射 ──────────────────────────────────

_OBJC_INTERFACE_TYPES = {'class_interface'}       # @interface Foo
_OBJC_IMPL_TYPES = {'class_implementation'}       # @implementation Foo
_OBJC_PROTOCOL_TYPES = {'protocol_declaration'}    # @protocol Foo
_OBJC_CATEGORY_TYPES = {'category_interface'}      # @interface Foo (Bar)

_JAVA_CLASS_TYPES = {'class_declaration'}
_JAVA_INTERFACE_TYPES = {'interface_declaration'}

# 每种语言的"顶层可提取符号"节点类型
SYMBOL_NODE_TYPES = {
    'objc': _OBJC_INTERFACE_TYPES | _OBJC_IMPL_TYPES | _OBJC_PROTOCOL_TYPES | _OBJC_CATEGORY_TYPES,
    'swift': {'class_declaration', 'protocol_declaration', 'extension_declaration',
              'function_declaration'},
    'java': _JAVA_CLASS_TYPES | _JAVA_INTERFACE_TYPES | {'method_declaration'},
    'kotlin': {'class_declaration', 'function_declaration', 'object_declaration'},
    'dart': {'class_definition', 'mixin_definition', 'function_declaration'},
    'cpp': {'class_specifier', 'function_definition', 'struct_specifier'},
    'python': {'class_definition', 'function_definition'},
    'ruby': {'class', 'module', 'method', 'singleton_method'},
    'javascript': {'class_declaration', 'function_declaration', 'method_definition',
                   'arrow_function'},
    'typescript': {'class_declaration', 'function_declaration', 'method_definition',
                   'interface_declaration', 'type_alias_declaration'},
    'go': {'type_declaration', 'function_declaration', 'method_declaration'},
    'rust': {'struct_item', 'function_item', 'impl_item', 'trait_item', 'enum_item'},
    'shell': set(),   # 无结构化符号
    'yaml': set(),
    'json': set(),
}

# 函数/方法级别节点 (用于"长文件按函数拆分")
FUNCTION_NODE_TYPES = {
    'objc': {'method_definition', 'method_declaration'},
    'swift': {'function_declaration'},
    'java': {'method_declaration', 'constructor_declaration'},
    'kotlin': {'function_declaration'},
    'dart': {'method_declaration', 'function_declaration'},
    'cpp': {'function_definition'},
    'python': {'function_definition'},
    'ruby': {'method', 'singleton_method'},
    'javascript': {'function_declaration', 'method_definition', 'arrow_function'},
    'typescript': {'function_declaration', 'method_definition'},
    'go': {'function_declaration', 'method_declaration'},
    'rust': {'function_item'},
    'shell': set(),
    'yaml': set(),
    'json': set(),
}

# ── 调用关系提取 ──────────────────────────────────────────────────

# 每种语言的"调用表达式"节点类型
CALL_NODE_TYPES = {
    'objc': {'message_expression'},
    'swift': {'call_expression', 'simple_identifier'},  # simple_identifier 需配合 call_suffix 判断
    'java': {'method_invocation'},
    'kotlin': {'call_expression'},
    'dart': {'method_invocation', 'function_invocation'},
    'cpp': {'call_expression'},
    'python': {'call'},
    'ruby': {'call', 'method_call'},
    'javascript': {'call_expression'},
    'typescript': {'call_expression'},
    'go': {'call_expression'},
    'rust': {'call_expression'},
    'shell': set(),
    'yaml': set(),
    'json': set(),
}

# 系统/框架方法名黑名单 — 调用图中过滤掉，避免噪音淹没业务调用
_SYSTEM_CALL_BLACKLIST = {
    # ObjC 系统方法
    'init', 'alloc', 'dealloc', 'release', 'retain', 'autorelease',
    'copy', 'mutableCopy', 'new', 'class', 'superclass', 'description',
    'hash', 'isEqual', 'isKindOfClass', 'isMemberOfClass', 'respondsToSelector',
    'performSelector', 'self', 'super',
    # UIKit/Foundation
    'addSubview', 'removeFromSuperview', 'layoutSubviews', 'setNeedsLayout',
    'layoutIfNeeded', 'setNeedsDisplay', 'setNeedsUpdateConstraints',
    'updateConstraints', 'didReceiveMemoryWarning', 'viewDidLoad',
    'viewWillAppear', 'viewDidAppear', 'viewWillDisappear', 'viewDidDisappear',
    'viewWillLayoutSubviews', 'viewDidLayoutSubviews',
    'initWithNibName', 'initWithCoder', 'awakeFromNib', 'prepareForSegue',
    'setBackgroundColor', 'setFrame', 'setHidden', 'setAlpha', 'setTransform',
    'setText', 'setFont', 'setTextColor', 'setImage', 'setTitle',
    # GCD/Threading
    'dispatch_async', 'dispatch_sync', 'dispatch_once', 'dispatch_after',
    'dispatch_get_main_queue', 'dispatch_get_global_queue',
    'NSLog', 'printf', 'print', 'NSAssert', 'NSCAssert',
    # ObjC 属性访问 (setter/getter via dot syntax)
    'count', 'length', 'firstObject', 'lastObject', 'objectAtIndex',
    'setObject', 'removeObject', 'addObject', 'containsObject',
    # Swift 系统方法
    'append', 'remove', 'insert', 'contains', 'filter', 'map', 'reduce',
    'sorted', 'forEach', 'compactMap', 'flatMap', 'joined', 'split',
    'isEmpty', 'hasPrefix', 'hasSuffix', 'lowercased', 'uppercased',
    'trimmingCharacters', 'components', 'replacingOccurrences',
    # Python 内置
    'len', 'range', 'enumerate', 'isinstance', 'hasattr', 'getattr', 'setattr',
    'type', 'str', 'int', 'float', 'bool', 'list', 'dict', 'set', 'tuple',
    'super', 'format', 'join', 'split', 'strip', 'replace',
    # JS/TS 内置
    'console.log', 'console.error', 'console.warn', 'console.info', 'console.debug',
    'JSON.parse', 'JSON.stringify', 'Object.keys', 'Object.values', 'Object.entries',
    'Array.isArray', 'Array.from', 'setTimeout', 'setInterval', 'clearTimeout',
    'parseInt', 'parseFloat', 'Promise.resolve', 'Promise.reject', 'Promise.all',
    # 通用
    'assert', 'throw', 'raise', 'return', 'break', 'continue',
    'get', 'set', 'update', 'delete', 'create',  # 过于泛化
}

# 接收器黑名单 (self / this / super 调用的系统方法也跳过)
_RECEIVER_BLACKLIST = {'self', 'this', 'super', '_'}


def _extract_call_name(node, code_bytes: bytes, language: str) -> str:
    """从调用节点中提取被调用的方法/函数名"""
    if language == 'objc':
        # tree-sitter-objc 的 message_expression 没有统一的 message_selector 节点；
        # selector 各部分分散为 identifier + : 对。
        # 策略: 收集所有后面紧跟 ':' 的 identifier，拼成完整 selector。
        # 对于简单调用 [self foo:bar]，self 后面是 identifier(foo) 而非 :，所以被正确过滤。
        # 对于嵌套调用 [[Obj method] foo:bar]，第一个 identifier 是 foo（后面是 :），也不会误判。
        children = list(node.children)
        selector_parts = []
        for i, child in enumerate(children):
            if child.type == 'identifier':
                if i + 1 < len(children) and children[i + 1].type == ':':
                    name = code_bytes[child.start_byte:child.end_byte].decode('utf-8', errors='replace')
                    selector_parts.append(f"{name}:")
        if selector_parts:
            return ''.join(selector_parts)
        return ''

    elif language == 'swift':
        # call_expression: 前缀 + call_suffix; simple_identifier + call_suffix 在后面过滤
        for child in node.children:
            if child.type == 'simple_identifier':
                return code_bytes[child.start_byte:child.end_byte].decode('utf-8', errors='replace')
            if child.type == 'navigation_expression':
                nav = code_bytes[child.start_byte:child.end_byte].decode('utf-8', errors='replace')
                return nav.split('.')[-1] if '.' in nav else nav
        return ''

    elif language in ('java', 'kotlin', 'dart', 'cpp'):
        for child in node.children:
            if child.type in ('identifier', 'template_function'):
                return code_bytes[child.start_byte:child.end_byte].decode('utf-8', errors='replace')
        return ''

    elif language == 'python':
        for child in node.children:
            if child.type == 'attribute':
                raw = code_bytes[child.start_byte:child.end_byte].decode('utf-8', errors='replace')
                return raw.split('.')[-1] if '.' in raw else raw
            if child.type == 'identifier':
                return code_bytes[child.start_byte:child.end_byte].decode('utf-8', errors='replace')
        return ''

    elif language in ('javascript', 'typescript'):
        for child in node.children:
            if child.type == 'member_expression':
                for sub in child.children:
                    if sub.type == 'property_identifier':
                        return code_bytes[sub.start_byte:sub.end_byte].decode('utf-8', errors='replace')
            if child.type == 'identifier':
                return code_bytes[child.start_byte:child.end_byte].decode('utf-8', errors='replace')
            if child.type == 'super':
                return 'super'
        return ''

    elif language == 'go':
        for child in node.children:
            if child.type == 'identifier':
                return code_bytes[child.start_byte:child.end_byte].decode('utf-8', errors='replace')
            if child.type == 'selector_expression':
                raw = code_bytes[child.start_byte:child.end_byte].decode('utf-8', errors='replace')
                return raw.split('.')[-1] if '.' in raw else raw
        return ''

    elif language == 'rust':
        for child in node.children:
            if child.type == 'identifier':
                return code_bytes[child.start_byte:child.end_byte].decode('utf-8', errors='replace')
            if child.type == 'field_expression':
                raw = code_bytes[child.start_byte:child.end_byte].decode('utf-8', errors='replace')
                return raw.split('.')[-1] if '.' in raw else raw
            if child.type == 'scoped_identifier':
                raw = code_bytes[child.start_byte:child.end_byte].decode('utf-8', errors='replace')
                return raw.split('::')[-1] if '::' in raw else raw
        return ''

    elif language == 'ruby':
        for child in node.children:
            if child.type == 'identifier':
                return code_bytes[child.start_byte:child.end_byte].decode('utf-8', errors='replace')
        return ''

    return ''


def _is_call_node(node, language: str) -> bool:
    """判断是否是有效的调用节点（含 Swift simple_identifier 特殊处理）"""
    call_types = CALL_NODE_TYPES.get(language, set())
    if node.type in call_types:
        if language == 'swift' and node.type == 'simple_identifier':
            # Swift 中 simple_identifier 只有紧跟 call_suffix 才是调用
            next_sibling = node.next_named_sibling
            if next_sibling and next_sibling.type == 'call_suffix':
                return True
            return False
        return True
    return False


def _extract_calls_in_range(code_bytes: bytes, language: str,
                             start_byte: int, end_byte: int) -> list[dict]:
    """提取指定字节范围内的所有方法/函数调用

    Returns:
        [{"name": "callee_name", "receiver": "self/ClassName/...", "line": N}, ...]
        去重 + 上限 30 条 + 系统方法黑名单过滤
    """
    try:
        parser = _get_cached_parser(language)
        tree = parser.parse(code_bytes)
        return _extract_calls_from_tree(tree.root_node, code_bytes, language, start_byte, end_byte)
    except Exception:
        return []


def _extract_calls_from_tree(root_node, code_bytes: bytes, language: str,
                              start_byte: int, end_byte: int) -> list[dict]:
    """从已解析的 AST root_node 中提取调用（复用 tree，避免重复解析）"""
    call_types = CALL_NODE_TYPES.get(language, set())
    if not call_types:
        return []

    calls = []
    seen = set()  # (name, line) 去重

    def _walk(node):
        if _is_call_node(node, language):
            if start_byte <= node.start_byte <= end_byte:
                name = _extract_call_name(node, code_bytes, language)
                if name and len(name) >= 1:
                    # 跳过单字符 + 系统黑名单
                    if name.lower() in _SYSTEM_CALL_BLACKLIST:
                        pass  # 系统方法，跳过
                    else:
                        line = node.start_point[0] + 1
                        key = (name, line)
                        if key not in seen:
                            seen.add(key)
                            calls.append({
                                'name': name,
                                'line': line,
                            })
        for child in node.children:
            _walk(child)

    _walk(root_node)
    return calls[:30]


# chunk_type 判断
def _get_chunk_type(node_type: str, language: str, code_bytes: bytes, node) -> str:
    """根据 AST 节点类型判断 chunk_type"""
    if language == 'objc':
        if node_type in _OBJC_INTERFACE_TYPES:
            return 'interface'
        if node_type in _OBJC_IMPL_TYPES:
            return 'implementation'
        if node_type in _OBJC_PROTOCOL_TYPES:
            return 'protocol'
        if node_type in _OBJC_CATEGORY_TYPES:
            return 'category'
    elif language == 'swift':
        if node_type == 'class_declaration':
            # 区分 class / extension: extension 有 'extension' keyword 子节点
            for child in node.children:
                if child.type == 'extension':
                    return 'extension'
            return 'class'
        if node_type == 'protocol_declaration':
            return 'protocol'
        if node_type == 'extension_declaration':
            return 'extension'
        if node_type == 'function_declaration':
            return 'function'
    elif language in ('java', 'kotlin'):
        if node_type in _JAVA_CLASS_TYPES or node_type == 'class_declaration':
            # 区分 interface / abstract class / class
            text = code_bytes[node.start_byte:node.end_byte].decode('utf-8', errors='replace')
            if 'interface ' in text.split('{')[0]:
                return 'interface'
            return 'class'
        if node_type == 'interface_declaration':
            return 'interface'
        if node_type in ('function_declaration', 'method_declaration', 'constructor_declaration'):
            return 'function'
        if node_type == 'object_declaration':
            return 'object'
    elif language == 'dart':
        if node_type == 'class_definition':
            return 'class'
        if node_type == 'mixin_definition':
            return 'mixin'
        if node_type in ('function_declaration', 'method_declaration'):
            return 'function'
    elif language == 'cpp':
        if node_type == 'class_specifier':
            return 'class'
        if node_type == 'struct_specifier':
            return 'struct'
        if node_type == 'function_definition':
            return 'function'
    elif language in ('python', 'ruby'):
        if node_type in ('class_definition', 'class', 'module'):
            return 'class'
        if node_type in ('function_definition', 'method', 'singleton_method'):
            return 'function'
    elif language in ('javascript', 'typescript'):
        if node_type in ('class_declaration', 'interface_declaration', 'type_alias_declaration'):
            return 'class'
        if node_type in ('function_declaration', 'method_definition', 'arrow_function'):
            return 'function'
    elif language == 'go':
        if node_type == 'type_declaration':
            return 'class'
        if node_type in ('function_declaration', 'method_declaration'):
            return 'function'
    elif language == 'rust':
        if node_type in ('struct_item', 'impl_item', 'trait_item', 'enum_item'):
            return 'class'
        if node_type == 'function_item':
            return 'function'
    return 'file'


# ── 工程类型自动检测 ───────────────────────────────────────────────

# 工程类型标志文件
_PROJECT_INDICATORS = {
    ('Podfile', '*.xcodeproj'): 'ios',
    ('Package.swift',): 'macos',
    ('build.gradle', 'build.gradle.kts', 'settings.gradle', 'settings.gradle.kts'): 'android',
    ('pubspec.yaml',): 'flutter',
    ('package.json',): 'javascript',
    ('Cargo.toml',): 'rust',
    ('go.mod',): 'go',
    ('CMakeLists.txt', 'Makefile'): 'generic',
    ('setup.py', 'pyproject.toml'): 'python',
    ('Gemfile',): 'ruby',
}


def auto_detect_project_type(repo_path: str) -> str:
    """根据目录下的标志文件自动判断工程类型。

    检查根目录下的标志文件，返回匹配的工程类型。
    无匹配时返回 'generic'。
    """
    if not os.path.isdir(repo_path):
        return 'generic'

    try:
        entries = set(os.listdir(repo_path))
    except (OSError, PermissionError):
        return 'generic'

    # 递归检查一级子目录中的标志文件 (用于 *.xcodeproj 等)
    try:
        for entry in os.listdir(repo_path):
            full = os.path.join(repo_path, entry)
            if os.path.isdir(full) and not entry.startswith('.'):
                entries.add(entry)
    except (OSError, PermissionError):
        pass

    best_type = 'generic'
    best_matched = 0  # 匹配的标志文件数，越多越可靠

    for indicators, ptype in _PROJECT_INDICATORS.items():
        matched = 0
        for ind in indicators:
            if ind.startswith('*.'):
                # 通配符：检查是否存在该后缀名的条目
                suffix = ind[1:]  # e.g. '.xcodeproj'
                if any(e.endswith(suffix) for e in entries):
                    matched += 1
            elif ind in entries:
                matched += 1
        if matched > best_matched:
            best_type = ptype
            best_matched = matched

    return best_type


# ── 目录扫描 ──────────────────────────────────────────────────────

def scan_directory(
    repo_path: str,
    project_type: str = 'generic',
    languages: Optional[list[str]] = None,
    skip_dirs: Optional[set[str]] = None,
    skip_extensions: Optional[set[str]] = None,
) -> list[dict]:
    """递归扫描目录，返回文件信息列表

    Returns:
        [{"path": abs_path, "rel_path": rel_to_repo, "language": str, "ext": str, "size": int, "mtime": float}, ...]
    """
    repo_path = os.path.abspath(repo_path)
    if not os.path.isdir(repo_path):
        raise ValueError(f"目录不存在: {repo_path}")

    # 合并跳过规则 — 从可配置规则中加载，支持运行时覆盖
    effective_skip_dirs = get_skip_dirs()
    effective_skip_exts = get_skip_exts()
    if skip_dirs:
        effective_skip_dirs |= skip_dirs
    if skip_extensions:
        effective_skip_exts |= skip_extensions

    # 有效语言集合
    allowed_langs = set(languages) if languages else None

    files = []
    stats = {"skipped_files": []}
    for root, dirs, filenames in os.walk(repo_path):
        # 原地修改 dirs 来跳过目录
        dirs[:] = [d for d in dirs if d not in effective_skip_dirs]

        for fname in filenames:
            ext = Path(fname).suffix.lower()
            if ext in effective_skip_exts:
                continue
            if ext not in EXTENSION_MAP:
                continue

            lang = EXTENSION_MAP[ext]
            if allowed_langs and lang not in allowed_langs:
                continue

            abs_path = os.path.join(root, fname)
            rel_path = os.path.relpath(abs_path, repo_path)

            # 跳过过大文件 (>100KB)
            try:
                size = os.path.getsize(abs_path)
                if size > 100 * 1024:
                    stats["skipped_files"].append({
                        "rel_path": rel_path,
                        "reason": f"过大 ({size // 1024}KB > 100KB)",
                        "size": size,
                    })
                    continue
                mtime = os.path.getmtime(abs_path)
            except OSError:
                continue

            files.append({
                'path': abs_path,
                'rel_path': rel_path,
                'language': lang,
                'ext': ext,
                'size': size,
                'mtime': mtime,
            })

    return files


# ── .h/.m 配对 ────────────────────────────────────────────────────

def pair_header_impl(files: list[dict]) -> dict[str, Optional[str]]:
    """建立 .h ↔ .m/.mm 配对关系

    Returns:
        {rel_path: paired_rel_path_or_None}
    """
    # 建立 basename → rel_path 的索引 (仅 .h 和 .m/.mm)
    headers = {}    # stem → rel_path
    impls = {}      # stem → rel_path

    for f in files:
        ext = f['ext']
        stem = Path(f['rel_path']).stem
        if ext == '.h':
            headers[stem] = f['rel_path']
        elif ext in ('.m', '.mm'):
            impls[stem] = f['rel_path']

    pairs = {}
    for f in files:
        ext = f['ext']
        stem = Path(f['rel_path']).stem
        if ext == '.h':
            pairs[f['rel_path']] = impls.get(stem)
        elif ext in ('.m', '.mm'):
            pairs[f['rel_path']] = headers.get(stem)
        else:
            pairs[f['rel_path']] = None

    return pairs


# ── AST 解析 + 符号提取 ───────────────────────────────────────────

def _get_node_name(node, code_bytes: bytes, language: str) -> str:
    """从 AST 节点中提取符号名称"""
    # 通用: 找 identifier / type_identifier / simple_identifier 子节点
    name_types = {'identifier', 'type_identifier', 'simple_identifier'}
    for child in node.children:
        if child.type in name_types:
            return code_bytes[child.start_byte:child.end_byte].decode('utf-8', errors='replace')

    # Swift: extension 的 name 在 user_type 里 (user_type 包含 type_identifier)
    if language == 'swift':
        for child in node.children:
            if child.type == 'user_type':
                # user_type 内部找 type_identifier
                for sub in child.children:
                    if sub.type in name_types:
                        return code_bytes[sub.start_byte:sub.end_byte].decode('utf-8', errors='replace')
                # fallback: 直接取 user_type 文本
                return code_bytes[child.start_byte:child.end_byte].decode('utf-8', errors='replace')

    # ObjC: class_interface 的 name 在 type_identifier 里
    if language == 'objc' and node.type in ('class_interface', 'class_implementation',
                                             'protocol_declaration', 'category_interface'):
        for child in node.children:
            if child.type == 'type_identifier':
                return code_bytes[child.start_byte:child.end_byte].decode('utf-8', errors='replace')

    return ''


def _extract_imports(node, code_bytes: bytes, language: str) -> list[str]:
    """提取 import/include 语句"""
    imports = []
    if language in ('objc', 'cpp'):
        for child in node.children:
            if child.type == 'preproc_include':
                text = code_bytes[child.start_byte:child.end_byte].decode('utf-8', errors='replace')
                imports.append(text.strip())
    elif language == 'swift':
        for child in node.children:
            if child.type == 'import_declaration':
                text = code_bytes[child.start_byte:child.end_byte].decode('utf-8', errors='replace')
                imports.append(text.strip())
    elif language in ('java', 'kotlin'):
        for child in node.children:
            if child.type == 'import_declaration':
                text = code_bytes[child.start_byte:child.end_byte].decode('utf-8', errors='replace')
                imports.append(text.strip())
    elif language == 'dart':
        for child in node.children:
            if child.type in ('import_specification', 'import_spec'):
                text = code_bytes[child.start_byte:child.end_byte].decode('utf-8', errors='replace')
                imports.append(text.strip())
    elif language == 'python':
        for child in node.children:
            if child.type in ('import_statement', 'import_from_statement'):
                text = code_bytes[child.start_byte:child.end_byte].decode('utf-8', errors='replace')
                imports.append(text.strip())
    elif language in ('javascript', 'typescript'):
        for child in node.children:
            if child.type == 'import_statement':
                text = code_bytes[child.start_byte:child.end_byte].decode('utf-8', errors='replace')
                imports.append(text.strip())
    elif language == 'go':
        for child in node.children:
            if child.type == 'import_declaration':
                text = code_bytes[child.start_byte:child.end_byte].decode('utf-8', errors='replace')
                imports.append(text.strip())
    elif language == 'rust':
        for child in node.children:
            if child.type == 'use_declaration':
                text = code_bytes[child.start_byte:child.end_byte].decode('utf-8', errors='replace')
                imports.append(text.strip())
    return imports


def _extract_symbols(code_bytes: bytes, language: str) -> list[dict]:
    """用 tree-sitter 提取顶层符号

    Returns:
        [{"name": str, "chunk_type": str, "line_start": int, "line_end": int,
          "start_byte": int, "end_byte": int, "node_type": str, "children": [...]}]
    """
    try:
        parser = _get_cached_parser(language)
    except Exception:
        return []

    tree = parser.parse(code_bytes)
    root = tree.root_node

    symbol_types = SYMBOL_NODE_TYPES.get(language, set())
    func_types = FUNCTION_NODE_TYPES.get(language, set())
    all_types = symbol_types | func_types

    symbols = []

    def _walk(node, parent_name=''):
        if node.type in symbol_types:
            name = _get_node_name(node, code_bytes, language) or f'_anon_{node.start_point[0]}'
            chunk_type = _get_chunk_type(node.type, language, code_bytes, node)

            # 提取子函数/方法 (用于类/接口/协议)
            children = []
            if node.type not in func_types:
                for child in node.children:
                    if child.type in func_types:
                        child_name = _get_node_name(child, code_bytes, language) or f'_anon_{child.start_point[0]}'
                        children.append({
                            'name': child_name,
                            'chunk_type': 'function',
                            'line_start': child.start_point[0] + 1,
                            'line_end': child.end_point[0] + 1,
                            'start_byte': child.start_byte,
                            'end_byte': child.end_byte,
                        })

            symbols.append({
                'name': name,
                'chunk_type': chunk_type,
                'line_start': node.start_point[0] + 1,
                'line_end': node.end_point[0] + 1,
                'start_byte': node.start_byte,
                'end_byte': node.end_byte,
                'node_type': node.type,
                'parent_class': parent_name,
                'children': children,
            })

            # 递归进入类/接口内部找嵌套符号
            for child in node.children:
                if child.type in all_types and child.type not in func_types:
                    _walk(child, parent_name=name)
        elif node.type in func_types and not parent_name:
            # 顶层函数 (不在任何类内部)
            name = _get_node_name(node, code_bytes, language) or f'_anon_{node.start_point[0]}'
            symbols.append({
                'name': name,
                'chunk_type': 'function',
                'line_start': node.start_point[0] + 1,
                'line_end': node.end_point[0] + 1,
                'start_byte': node.start_byte,
                'end_byte': node.end_byte,
                'node_type': node.type,
                'parent_class': '',
                'children': [],
            })

    for child in root.children:
        _walk(child)

    return symbols


# ── 混合分块策略 ──────────────────────────────────────────────────

MAX_CHUNK_SIZE = 1000   # 单 chunk 最大字符数
SUB_CHUNK_SIZE = 500    # 超长 chunk 二次切分大小


def _sub_chunk(text: str, size: int = SUB_CHUNK_SIZE) -> list[str]:
    """超长 chunk 二次切分 (按行边界，超长行按字符位置硬切)"""
    if len(text) <= size:
        return [text]

    chunks = []
    lines = text.split('\n')
    current = ''
    for line in lines:
        if len(current) + len(line) + 1 > size:
            if current:
                chunks.append(current)
            # 单行超长(如 573KB 单行 JSON): 按字符位置硬切
            if len(line) > size:
                for k in range(0, len(line), size):
                    chunks.append(line[k:k+size])
                current = ''
            else:
                current = line
        else:
            current = current + '\n' + line if current else line
    if current:
        chunks.append(current)

    return chunks if chunks else [text[:size]]


def _make_display_text(
    rel_path: str,
    chunk_type: str,
    symbol_name: str,
    line_start: int,
    line_end: int,
    content: str,
    language: str,
) -> str:
    """构造带上下文头部的 display_text，用于 embedding 提升检索质量

    注释会被剥离——中文注释/字符串字面量会误导跨语言 embedding 模型
    （如中文 query 匹配代码里的中文注释而非符号语义）。
    """
    if language in ('python', 'ruby', 'shell', 'yaml', 'json'):
        prefix = '#'
        clean_content = _HASH_COMMENT_RE.sub('', content)
    else:
        prefix = '//'
        clean_content = _C_COMMENT_RE.sub('', content)

    # 剥离中文字符串（硬编码字符串/测试数据，干扰跨语言检索）
    clean_content = _CN_STRIP_RE.sub('', clean_content)

    if chunk_type == 'file':
        type_info = 'file'
    else:
        type_info = f"{chunk_type}: {symbol_name}"

    header = f"{prefix} File: {rel_path} | {type_info} | Lines {line_start}-{line_end}"
    return f"{header}\n{clean_content}"


def chunk_code(
    code_bytes: bytes,
    language: str,
    rel_path: str,
    repo_name: str = '',
    project_type: str = '',
    repo_path: str = '',
    paired_file: str = '',
) -> list[dict]:
    """核心分块函数

    策略:
    - 短文件 (<500字符) → 整文件一个 chunk
    - 有结构的文件 → 按顶层符号拆分
    - 超长符号 (>1000字符) → 按 500 字符二次切分

    Returns:
        [{id, repo_name, project_type, file_path, file_name, language,
          chunk_type, symbol_name, content, line_start, line_end, metadata}]
    """
    code_text = code_bytes.decode('utf-8', errors='replace')
    file_size = len(code_bytes)
    ext = Path(rel_path).suffix.lower()
    file_name = Path(rel_path).name
    is_header = (ext == '.h')

    base_meta = {
        'file_size_bytes': file_size,
        'repo_path': repo_path,
        'is_header': is_header,
    }
    if paired_file:
        base_meta['paired_file'] = paired_file

    # ── 短文件: 整文件一个 chunk (用字符数判断) ──
    if len(code_text) < 500:
        chunk_id = f"{repo_name}_{rel_path}___0"  # 统一格式: parent=_ , symbol=空
        line_count = code_text.count('\n') + 1
        return [{
            'id': chunk_id,
            'repo_name': repo_name,
            'project_type': project_type,
            'file_path': rel_path,
            'file_name': file_name,
            'language': language,
            'chunk_type': 'file',
            'symbol_name': file_name,
            'content': code_text,
            'display_text': _make_display_text(rel_path, 'file', file_name, 1, line_count, code_text, language),
            'line_start': 1,
            'line_end': line_count,
            'metadata': {**base_meta},
        }]

    # ── 尝试 AST 解析（仅对注册了符号类型的语言，如 JSON 直接走降级分块）──
    symbol_types = SYMBOL_NODE_TYPES.get(language, set())
    func_types = FUNCTION_NODE_TYPES.get(language, set())
    if symbol_types or func_types:
        symbols = _extract_symbols(code_bytes, language)
    else:
        symbols = []  # 无符号类型 → 跳过 tree-sitter 解析，避免海量 Node 引用环堆积

    # ── AST 解析失败/无符号: 降级为整文件 chunk ──
    if not symbols:
        base_meta['parse_warning'] = 'tree-sitter parse failed, fallback to file chunk'
        chunks = _sub_chunk(code_text)
        result = []
        for i, chunk_text in enumerate(chunks):
            # 简单计算行号
            prefix = '\n'.join(code_text.split('\n')[:0])  # 不精确但够用
            chunk_id = f"{repo_name}_{rel_path}___{i}"
            line_count = code_text.count('\n') + 1
            result.append({
                'id': chunk_id,
                'repo_name': repo_name,
                'project_type': project_type,
                'file_path': rel_path,
                'file_name': file_name,
                'language': language,
                'chunk_type': 'file',
                'symbol_name': file_name,
                'content': chunk_text,
                'display_text': _make_display_text(rel_path, 'file', file_name, 1, line_count, chunk_text, language),
                'line_start': 1,  # 降级模式下不精确追踪行号
                'line_end': line_count,
                'metadata': {**base_meta},
            })
        return result

    # ── 有符号: 按符号拆分 ──
    result = []
    lines = code_text.split('\n')

    # 提取 imports + 全文件调用关系（复用同一次 tree-sitter parse）
    try:
        _tree = _get_cached_parser(language).parse(code_bytes)
        imports = _extract_imports(_tree.root_node, code_bytes, language)
        # 复用 root_node 提取全文件调用（避免二次 parse）
        all_file_calls = _extract_calls_from_tree(
            _tree.root_node, code_bytes, language, 0, len(code_bytes)
        )
    except Exception:
        imports = []
        all_file_calls = []
    base_meta['imports_count'] = len(imports)
    if imports:
        base_meta['imports'] = imports[:20]  # 限制数量

    for sym_idx, sym in enumerate(symbols):
        chunk_content = code_bytes[sym['start_byte']:sym['end_byte']].decode('utf-8', errors='replace')

        # 构造 chunk id: {repo}_{file}_{parent_class}_{symbol}_{idx}
        parent = sym['parent_class'] or '_'
        chunk_id = f"{repo_name}_{rel_path}_{parent}_{sym['name']}_{sym_idx}"

        sym_meta = {**base_meta}
        if sym['parent_class']:
            sym_meta['parent_class'] = sym['parent_class']

        # 过滤归属当前符号的调用（只保留符号体内的调用，排除子符号体内的）
        sym_calls = [c for c in all_file_calls
                     if sym['start_byte'] <= _estimate_byte_pos(code_text, c['line'])
                     <= sym['end_byte']]
        if sym_calls:
            sym_meta['calls'] = sym_calls[:20]  # 每个符号最多保留 20 条调用

        # 超长符号二次切分
        if len(chunk_content) > MAX_CHUNK_SIZE:
            sub_chunks = _sub_chunk(chunk_content)
            for sub_idx, sub_text in enumerate(sub_chunks):
                sub_id = f"{chunk_id}_{sub_idx}"
                result.append({
                    'id': sub_id,
                    'repo_name': repo_name,
                    'project_type': project_type,
                    'file_path': rel_path,
                    'file_name': file_name,
                    'language': language,
                    'chunk_type': sym['chunk_type'],
                    'symbol_name': sym['name'],
                    'content': sub_text,
                    'display_text': _make_display_text(rel_path, sym['chunk_type'], sym['name'], sym['line_start'], sym['line_end'], sub_text, language),
                    'line_start': sym['line_start'],
                    'line_end': sym['line_end'],
                    'metadata': {**sym_meta},
                })
        else:
            result.append({
                'id': chunk_id,
                'repo_name': repo_name,
                'project_type': project_type,
                'file_path': rel_path,
                'file_name': file_name,
                'language': language,
                'chunk_type': sym['chunk_type'],
                'symbol_name': sym['name'],
                'content': chunk_content,
                'display_text': _make_display_text(rel_path, sym['chunk_type'], sym['name'], sym['line_start'], sym['line_end'], chunk_content, language),
                'line_start': sym['line_start'],
                'line_end': sym['line_end'],
                'metadata': {**sym_meta},
            })

    return result


def _estimate_byte_pos(code_text: str, line_number: int) -> int:
    """估算第 N 行的起始字节位置（用于调用归属过滤）

    tree-sitter 的 start_byte/end_byte 是 UTF-8 字节偏移，所以必须用
    编码后字节数计算，不能直接用 Python 字符串 len()（字符数）。
    """
    lines = code_text.split('\n')
    pos = 0
    for i in range(min(line_number - 1, len(lines))):
        pos += len(lines[i].encode('utf-8')) + 1  # +1 for \n
    return pos


# ── 主入口: 扫描 + 解析 + 分块 ────────────────────────────────────

def parse_repo(
    repo_name: str,
    repo_path: str,
    project_type: str = '',
    languages: Optional[list[str]] = None,
    skip_dirs: Optional[set[str]] = None,
    skip_extensions: Optional[set[str]] = None,
) -> tuple[list[dict], dict]:
    """扫描仓库并解析所有代码文件

    project_type 为空时自动检测。
    """
    repo_path = os.path.abspath(repo_path)

    # 自动检测工程类型
    if not project_type:
        project_type = auto_detect_project_type(repo_path)

    # 1. 扫描文件
    files = scan_directory(repo_path, project_type, languages, skip_dirs, skip_extensions)

    # 2. 建立 .h/.m 配对
    pairs = pair_header_impl(files)

    # 3. 逐文件解析分块
    all_chunks = []
    stats = {
        'total_files': len(files),
        'total_chunks': 0,
        'by_language': {},
        'by_chunk_type': {},
        'skipped_files': [],
        'parse_warnings': 0,
    }

    for f in files:
        try:
            with open(f['path'], 'rb') as fh:
                code_bytes = fh.read()
        except (OSError, PermissionError) as e:
            stats['skipped_files'].append({'path': f['rel_path'], 'reason': str(e)})
            continue

        if not code_bytes.strip():
            continue

        paired = pairs.get(f['rel_path'], '')

        chunks = chunk_code(
            code_bytes=code_bytes,
            language=f['language'],
            rel_path=f['rel_path'],
            repo_name=repo_name,
            project_type=project_type,
            repo_path=repo_path,
            paired_file=paired or '',
        )

        for c in chunks:
            if c['metadata'].get('parse_warning'):
                stats['parse_warnings'] += 1

        all_chunks.extend(chunks)

        # 统计
        lang = f['language']
        stats['by_language'][lang] = stats['by_language'].get(lang, 0) + len(chunks)
        for c in chunks:
            ct = c['chunk_type']
            stats['by_chunk_type'][ct] = stats['by_chunk_type'].get(ct, 0) + 1

    stats['total_chunks'] = len(all_chunks)
    return all_chunks, stats
