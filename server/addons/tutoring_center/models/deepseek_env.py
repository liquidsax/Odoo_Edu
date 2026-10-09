"""DeepSeek 密钥的 .env 读写。不碰 Odoo，也不把密钥写进日志。

网页保存走这里：文件名必须是 `.env`，权限 0600，拒绝符号链接。
进程要立刻生效，由调用方在写成功之后再改 os.environ。
"""
import os
import re
import tempfile

ENV_KEY = 'DEEPSEEK_API_KEY'
ENV_FILE_OVERRIDE = 'TUTORING_DEEPSEEK_ENV_FILE'

_KEY_RE = re.compile(r'^[A-Za-z0-9._-]{16,200}$')
_KEY_LINE = re.compile(r'^(?:export\s+)?DEEPSEEK_API_KEY\s*=')


def normalize_api_key(value):
    """空、过短、带空格或换行的一律拒绝。异常文本里不回显密钥。"""
    if not isinstance(value, str):
        raise ValueError('请粘贴 DeepSeek 的 API Key。')
    key = value.strip()
    if not key:
        raise ValueError('密钥不能为空。')
    if '\n' in value or '\r' in value or ' ' in key:
        raise ValueError('密钥里不能有空格或换行。')
    if not _KEY_RE.fullmatch(key):
        raise ValueError('这串内容的长度或字符不像 DeepSeek 的 API Key。')
    return key


def mask_secret(key):
    """页面上只留末四位。不够四位就整段打成星号，调用方拿不到原文。"""
    if not key:
        return '未配置'
    if len(key) < 4:
        return '****'
    return '****' + key[-4:]


def read_env_file(path):
    """KEY=VALUE。缺文件当空；注释与 export 前缀都认。值本身不会写日志。"""
    if not path or not os.path.isfile(path) or os.path.islink(path):
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            lines = handle.read().splitlines()
    except UnicodeDecodeError as exc:
        raise ValueError('现有的 .env 不是 UTF-8。') from exc
    found = {}
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('export '):
            line = line[len('export '):].strip()
        if '=' not in line:
            continue
        name, value = line.split('=', 1)
        name = name.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in '"\'':
            value = value[1:-1]
        if name:
            found[name] = value
    return found


def write_env_key(path, key):
    """把 DEEPSEEK_API_KEY 写进指定的 .env，其它行原样保留。"""
    key = normalize_api_key(key)
    path = os.path.abspath(path)
    if os.path.basename(path) != '.env':
        raise ValueError('密钥文件名必须是 .env。')
    if os.path.islink(path):
        raise ValueError('不能把密钥写到符号链接上。')
    directory = os.path.dirname(path)
    if not os.path.isdir(directory):
        raise ValueError('密钥文件所在的目录不存在。')
    if os.path.isdir(path):
        raise ValueError('密钥路径是一个目录，无法写入。')

    lines = []
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as handle:
                lines = handle.read().splitlines()
        except UnicodeDecodeError as exc:
            raise ValueError('现有的 .env 不是 UTF-8，已停止写入，避免把别的配置冲掉。') from exc

    written = False
    kept = []
    for line in lines:
        if _KEY_LINE.match(line.strip()):
            if not written:
                kept.append('%s=%s' % (ENV_KEY, key))
                written = True
            continue
        kept.append(line)
    if not written:
        if kept and kept[-1] != '':
            kept.append('')
        kept.append('%s=%s' % (ENV_KEY, key))
    data = '\n'.join(kept) + '\n'

    fd, tmp = tempfile.mkstemp(prefix='tmp-deepseek-', dir=directory)
    tmp_left = tmp
    try:
        # 写之前就把权限收紧，别留一个谁都能读的窗口。Windows 没有 os.fchmod，
        # mkstemp 建的临时文件本来就只属于当前用户，跳过即可（本机踩过：AttributeError 直接 500）
        if hasattr(os, 'fchmod'):
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            handle.write(data)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
        tmp_left = None
    finally:
        if tmp_left and os.path.exists(tmp_left):
            try:
                os.unlink(tmp_left)
            except OSError:
                pass
    os.chmod(path, 0o600)
    return path
