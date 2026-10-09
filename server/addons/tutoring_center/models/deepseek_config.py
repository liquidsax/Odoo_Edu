"""错题摘要与智能画图共用的 DeepSeek 配置。

读密钥的顺序（先有值的赢）：
1. 进程环境变量 DEEPSEEK_API_KEY（启动时注入，或本进程里管理员刚保存写进去的）
2. .env 文件里的 DEEPSEEK_API_KEY（每次现读，改文件不必重启）
3. 系统参数 tutoring_center.deepseek_api_key（错题功能原来的兜底）

默认文件在本模块目录下的 `.env`。Docker 开发环境只把模块目录挂进容器，
所以这个位置容器里能看见；仓库根那个给 compose 做变量替换的 `.env` 看不见。
路径可用环境变量 TUTORING_DEEPSEEK_ENV_FILE，或系统参数
tutoring_center.deepseek_env_file 改掉，文件名仍然必须是 `.env`。
"""
import logging
import os

from odoo.modules.module import get_module_path

from .deepseek_env import ENV_FILE_OVERRIDE, ENV_KEY, read_env_file
from .plot_expr import clean_api_url, clean_model_id

_logger = logging.getLogger(__name__)

ICP_KEY = 'tutoring_center.deepseek_api_key'
ICP_MODEL = 'tutoring_center.deepseek_model'
ICP_URL = 'tutoring_center.deepseek_base_url'
ICP_ENV_FILE = 'tutoring_center.deepseek_env_file'
ICP_PLOT_MODEL = 'tutoring_center.deepseek_plot_model'

# 官方文档（Models & Pricing）把 DeepSeek-V4.1-Flash 的接口名写成 deepseek-flash。
# 不另造一个「v4.1」的 id；要换模型就填 tutoring_center.deepseek_plot_model。
DEFAULT_MODEL = 'deepseek-flash'
DEFAULT_URL = 'https://api.deepseek.com/v1/chat/completions'


def default_env_path():
    """模块自己的目录，而不是写死某台机器的盘符。"""
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    located = get_module_path('tutoring_center', display_warning=False)
    return os.path.join(located or here, '.env')


def env_file_path(env):
    override = (os.environ.get(ENV_FILE_OVERRIDE) or '').strip()
    if not override:
        override = (env['ir.config_parameter'].sudo().get_param(ICP_ENV_FILE, '') or '').strip()
    if override:
        return os.path.abspath(override)
    return os.path.abspath(default_env_path())


def _file_key(path):
    try:
        return (read_env_file(path).get(ENV_KEY) or '').strip()
    except (OSError, ValueError):
        _logger.warning('DeepSeek 密钥文件读失败，已跳过文件这一层')
        return ''


def deepseek_settings(env, model_param=None):
    """返回 key/model/url/source/env_file。source 只说明钥匙从哪一层来，不含钥匙本身。"""
    icp = env['ir.config_parameter'].sudo()
    path = env_file_path(env)
    env_key = (os.environ.get(ENV_KEY) or '').strip()
    file_key = _file_key(path)
    param_key = (icp.get_param(ICP_KEY, '') or '').strip()
    if env_key:
        key, source = env_key, 'env'
    elif file_key:
        key, source = file_key, 'file'
    elif param_key:
        key, source = param_key, 'param'
    else:
        key, source = '', 'none'

    chosen = ''
    if model_param:
        chosen = icp.get_param(model_param, '') or ''
    shared = icp.get_param(ICP_MODEL, '') or ''
    model = clean_model_id(chosen, '') or clean_model_id(shared, DEFAULT_MODEL)
    url = clean_api_url(icp.get_param(ICP_URL, '') or '', DEFAULT_URL)
    return {
        'key': key,
        'model': model,
        'url': url,
        'source': source,
        'env_file': path,
    }
