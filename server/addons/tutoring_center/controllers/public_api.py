"""机构门面：给**手上还没有 Key 的潜在客户**看的那一屏，以及他们的试听课预约。

与 `api.py` 的分工只有一处，但那处很重要：`api.py` 的前提是"调用方拿着一把
Odoo API Key"，所以它零 `sudo()`、全靠记录规则说话。这一层做不到——来看门面的家长
没有 Key，而 PUBLIC 用户既读不到 `product.template`，也读不到这份联系人。
于是这里出现 `sudo()`，范围钉死成两条：

1. 只读门面这三样东西（本机构联系人、打了师资标签的联系人、服务类商品），
   并且**逐字段白名单**回吐：`tutoring.*` 的**任何一行记录**都不从这里出去，
   学生、错题、知识库在这条通道上根本不可达。唯一例外是年级那张 *常量表*
   （模型定义里的 selection，不是任何人的数据）——小程序的表单选项必须和
   `/meta` 同源，不该在客户端写死第二份；
2. 唯一的写入是建一条 `crm.lead`，字段同样只有白名单那几个。

内容全在 Odoo 原生件上（机构=`res.company` 的联系人，师资=联系人标签，
服务=服务类商品），网页端不再为这些做第二套页面：小程序这一屏就是它们的第一处消费方。

三条纪律与 `api.py` 同源，直接复用它的信封，不写第二份：`X-R3ynA-Client` 照旧要；
`auth='public'` 天然不会 302 到登录页，所以这层不会踩"401 的响应体是 HTML"那个坑。

**已知代价**：`POST trial` 没有防刷（无人能验真，也没有验证码）。演示与留资阶段接受，
真上线对外再谈限流，别提前给它加一套没人要的机制。
"""

import logging
import re

from markupsafe import Markup, escape

from odoo import _, http
from odoo.http import request

from ..models.tutoring_knowledge import GRADE_SELECTION
from ..models.tutoring_library_item import b64_head, sniff_image_mimetype
from .api import _error, _guard, _ok, _read_json_body

_logger = logging.getLogger(__name__)

# 师资不是另一个模型，就是打了这个标签的联系人：老板在「联系人」里勾标签即可，
# 不必新增字段、不必改视图。查不到这个标签时师资列表为空——那是"还没设置"，不是报错。
TEAM_TAG_NAME = '师资展示'

GRADE_LABELS = dict(GRADE_SELECTION)

# 公开写入口的每个字段各自封顶：来路不明的体不该把线索描述写成几 MB
MAX_LEN = {
    'name': 40,
    'phone': 32,
    'grade': 24,
    'when': 40,
    'note': 500,
}


def _plain(value):
    """Html/Text → 一行纯文本。

    机构简介与老师介绍存在 `res.partner.comment`（原生就是 Html），小程序卡片上
    要的是纯文本，所以剥标签并把连续空白压成一格；剥完是空的就回 False，
    让客户端画占位而不是显示一个空框。
    """
    if not value:
        return False
    text = re.sub(r'\s+', ' ', str(Markup(value).striptags())).strip()
    return text or False


def _text(value, limit):
    """不可信的公开入参 → 压掉换行、截断；空值一律 False。"""
    if value is None or value is False:
        return False
    text = re.sub(r'\s+', ' ', str(value)).strip()
    return text[:limit] or False


def _image(value):
    """Binary（base64）→ data URI；认类型认文件头，不认扩展名。

    直接吐 base64 而不是一条图片 URL：这一屏的图就 logo 加几张头像，
    再开一条 `/image/<id>` 的路由等于把同一样东西放到两个地址上。
    """
    if not value:
        return False
    if isinstance(value, memoryview):
        value = bytes(value)
    if isinstance(value, bytes):
        text = value.decode('ascii', 'ignore')
    else:
        text = str(value)
    mime = sniff_image_mimetype(b64_head(text, 16)) or 'image/png'
    return 'data:%s;base64,%s' % (mime, text.strip())


class TutoringPublicApi(http.Controller):

    # ------------------------------------------------------------
    # 门面整屏
    # ------------------------------------------------------------

    @http.route('/r3yna/api/public/institution', type='http', auth='public',
                methods=['GET'], csrf=False, readonly=True)
    def api_institution(self, **kw):
        """一个响应喂整屏（介绍 + 教什么 + 服务清单 + 师资 + 位置）。

        刻意不分四条：潜在客户打开小程序只有一次首屏，四条路由就是一次打开打四个请求，
        而其中任何一条失败都会让这一屏缺一块——`library` 那条"一个响应喂一整屏"
        已经是这个接口层的既有口径，这里跟着走。
        """
        guarded = _guard()
        if guarded:
            return guarded
        company = request.env.company.sudo()
        services = self._services(company)
        return _ok(
            institution=self._brief(company),
            services=services,
            subjects=sorted({one['category'] for one in services if one['category']}),
            team=self._team(company),
            grades=[{'value': value, 'label': label} for value, label in GRADE_SELECTION],
        )

    @staticmethod
    def _brief(company):
        partner = company.partner_id
        return {
            'name': partner.name or company.name,
            'intro': _plain(partner.comment),
            'phone': (partner.phone or '').strip() or False,
            'email': (partner.email or '').strip() or False,
            'address': TutoringPublicApi._address(partner),
            # 小程序的地图要的是经纬度（wx.openLocation），地址只是给人看的那一行
            'lat': partner.partner_latitude or False,
            'lng': partner.partner_longitude or False,
            'logo': _image(partner.image_256),
        }

    @staticmethod
    def _address(partner):
        return ' '.join(
            part for part in [
                partner.country_id.name if partner.country_id else False,
                partner.state_id.name if partner.state_id else False,
                partner.city,
                partner.zip,
                partner.street,
            ] if part
        ) or False

    def _team(self, company):
        Category = request.env['res.partner.category'].sudo()
        tag = Category.search([('name', '=', TEAM_TAG_NAME)], limit=1)
        if not tag:
            return []
        partners = request.env['res.partner'].sudo().search([
            ('category_id', 'in', tag.id),
            ('active', '=', True),
            ('id', '!=', company.partner_id.id),
        ], order='name')
        return [self._team_item(partner, tag) for partner in partners]

    @staticmethod
    def _team_item(partner, tag):
        return {
            'name': partner.name,
            'title': (partner.function or '').strip() or False,
            'intro': _plain(partner.comment),
            # 同一排标签里，除了"上不上门面"这个管理用的，剩下的都是给家长看的教科目
            'subjects': [c.name for c in partner.category_id if c.id != tag.id],
            'photo': _image(partner.image_256),
        }

    @staticmethod
    def _services(company):
        templates = request.env['product.template'].sudo().search([
            ('active', '=', True),
            ('type', '=', 'service'),
        ], order='name')
        symbol = company.currency_id.symbol or ''
        return [{
            'id': product.id,
            'name': product.name,
            'intro': _plain(product.description_sale),
            'price': product.list_price,
            'currency': symbol,
            'category': product.categ_id.name or False,
            'image': _image(product.image_128),
        } for product in templates]

    # ------------------------------------------------------------
    # 预约试听（留资）
    # ------------------------------------------------------------

    @http.route('/r3yna/api/public/trial', type='http', auth='public',
                methods=['POST'], csrf=False, readonly=False)
    def api_trial(self, **kw):
        """家长填的这张表落进 `crm.lead`——**不另建一张咨询表**。

        真源只有一份：老板下一批要的客户管理就是同一个 CRM 看板，
        在手机上新立一张"预约表"等于把同一件事开成两个入口，两边都会漏。
        意向课程只认这个库里真在展示的服务：传进来一个不存在或已下架的 id
        就当没选，不报错、也不靠猜 id 命中别的东西。
        """
        guarded = _guard()
        if guarded:
            return guarded
        if 'crm.lead' not in request.env:
            return _error(503, 'booking_unavailable', _('平台暂时不受理预约，请稍后再试。'))
        payload = _read_json_body()
        if payload is None:
            return _error(400, 'bad_json', _('请求体不是合法的 JSON 对象。'))

        name = _text(payload.get('name'), MAX_LEN['name'])
        phone = _text(payload.get('phone'), MAX_LEN['phone'])
        if not name or not phone:
            return _error(400, 'incomplete', _('称呼和手机号都要填，不然没法回你。'))
        if sum(char.isdigit() for char in phone) < 7:
            return _error(400, 'bad_phone', _('手机号看起来短了，再核对一下？'))
        grade_value = _text(payload.get('grade'), MAX_LEN['grade'])
        # 客户端传的是 selection 的值（"07" 这种），落到线索里要写人看得懂的那一面；
        # 认不出的就当自由文本留着，不把家长填的东西丢掉
        grade = GRADE_LABELS.get(grade_value) or grade_value
        when = _text(payload.get('when'), MAX_LEN['when'])
        note = _text(payload.get('note'), MAX_LEN['note'])

        service = False
        try:
            service_id = int(payload.get('service_id'))
        except (TypeError, ValueError):
            service_id = 0
        if service_id:
            found = request.env['product.template'].sudo().search([
                ('id', '=', service_id),
                ('active', '=', True),
                ('type', '=', 'service'),
            ], limit=1)
            service = found.name if found else False

        lines = [_('来源：微信小程序 · 机构门面页'), _('称呼：%s', name), _('手机号：%s', phone)]
        if service:
            lines.append(_('意向课程：%s', service))
        if grade:
            lines.append(_('年级：%s', grade))
        if when:
            lines.append(_('期望时间：%s', when))
        if note:
            lines.append(_('备注：%s', note))

        title = ' · '.join(part for part in [_('小程序试听预约'), name, service or grade] if part)
        try:
            request.env['crm.lead'].sudo().create({
                'name': title,
                'contact_name': name,
                'phone': phone,
                'type': 'lead',
                'description': '<br/>'.join(escape(line) for line in lines),
            })
        except Exception:
            # 公开接口不该把后端的堆栈讲给陌生人听，但这条得留在日志里，
            # 不然"家长说提交失败、我们什么都看不见"会是最难查的一种坏。
            _logger.exception('小程序试听预约写入失败')
            return _error(500, 'rejected', _('这条预约没能收下，稍后再试一次。'))
        return _ok(received=True)
