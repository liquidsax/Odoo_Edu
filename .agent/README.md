# Odoo 19 本机操作说明

> 环境：Windows + Odoo 19 **Community（社区版）** + PostgreSQL 18，安装于 `E:\Odoo`。
> 本文所有事实均取自本机实测（2026-09-29 更新）。改配置前请先读完第九节「坑」。
> 系统当前定位与改造明细见同目录 `handoff.md`（R3ynA 学习平台）。

---

## 一、访问与登录

| 项目 | 值 |
|---|---|
| 地址 | http://127.0.0.1:8069 |
| 局域网访问 | `http_interface = 0.0.0.0`，可用 `http://<本机IP>:8069` |
| 数据库管理器 | http://127.0.0.1:8069/web/database/manager |
| 管理员密码 | `odoo.conf` 中 `admin_passwd` 原值（用于创建/备份/恢复/删除数据库） |
| 业务库 | `OdooForDB` |
| 后台账号 | `admin`（超管）、`__system__`(机器人)、`public`、`portaltemplate` |
| 门户账号 | `biaodi` / `Biaodi@2026`（学生"表弟"）；`student02` / `Student@2026`（示例学生B） |
| 语言 / 数据 | 中文 `zh_CN`，`with_demo = False`（演示数据为自建，见 handoff 第四节） |

网站首页为"R3ynA 学习平台"门面；学生/家长从导航"学习平台"直达自己的学习数据页（`/my/learning`）。

---

## 二、界面三大入口

1. **R3ynA 学习**（默认应用）—— 后台顶栏是 **学生 / 错题 / 练习册 / 知识点 / 错因**，教师日常工作都在这里。
2. **联系人** —— 已按辅导场景精简：姓名 / 电话（家长）/ 学校 / 关联学生。
3. **设置** —— 公司信息、用户与权限、技术参数（开发者模式）。

> 应用切换器当前只显示 **R3ynA 学习 / 联系人 / 网站**。"应用"入口及讨论/项目/邮件营销/调查/员工/仪表板等应用菜单被隐藏（模块仍安装，见第六节权限组），恢复方法见第四节。

---

## 三、当前已装能力（45 个模块，9 个应用）

| 应用 | 说明 |
|---|---|
| **tutoring_center R3ynA 学习平台**（自定义） | 学生档案、知识点、错因字典、辅导课次、学校考试、错题记录、门户学习页 |
| **Contacts 联系人** | 门户联系人主数据（精简视图） |
| **Website 网站** | 教育平台门面、导航"学习平台" |
| **Discuss 讨论** | `mail`/`bus`，单据 chatter 底层（菜单已隐藏） |
| **Project / Email Marketing / Survey / HR** | 仍安装（提供 chatter/活动等底层依赖），**菜单全部隐藏**，业务上不再使用 |
| **Portal 门户** | 外部学生/家长登录查看学习数据，按联系人硬隔离 |
| 平台类 | `base`、`web`、`portal`、`http_routing`、`website_*` 等技术模块 |

模块统计（`ir_module_module`）：

| state | 数量 | 含义 |
|---|---|---|
| `installed` | 45 | 已启用 |
| `uninstalled` | 646 | 可安装，代码在本机 |
| `uninstallable` | 23 | 代码缺失（企业版），装不了 |

> 2026-09-29 上午已卸载 30 个模块（短信/纸质信件/双向认证/通行密钥/邮件营销主题/实况聊天/HR 扩展等），明细见 `handoff.md` 第九节。

---

## 四、如何启用更多应用（离线，无需下载）

1. **恢复"应用"菜单**：设置 → 用户 → 编辑当前用户 → 勾选 **"显示全部应用菜单"** 组（`tutoring_center.group_show_hidden_apps`）→ 刷新页面。用完建议取消勾选，恢复精简界面。
2. Apps 页搜索模块名 → 点 **启用 / Activate** → 等待安装完成。
3. 列表里找不到模块 → 点 Apps 页顶部 **「更新应用列表 / Update Apps List」** 重扫 `addons` 目录。

本机 `addons_path` 含两个目录：`e:\odoo\server\odoo\addons`（官方 692 个模块）+ `E:\Odoo\server\addons`（自定义模块，tutoring_center 所在地）。磁盘上另有 `account`、`sale_management`、`stock`、`mrp` 等常用业务模块可随时安装，但对当前辅导场景无必要。

---

## 五、装不了的功能（企业版，本机无源码）

数据库中有 23 个 `uninstallable` 模块，属 Odoo **Enterprise**，**代码不在磁盘上，点了也装不了**。
要启用需：购买授权 → 获取 `enterprise` 源码目录 → 加入 `addons_path` → 重启 Odoo → 更新应用列表。

```
helpdesk  knowledge  sign  web_studio  planning  appointment
quality  quality_control  mrp_plm  mrp_workorder
account_accountant  hr_appraisal  timesheet_grid  marketing_automation
sale_subscription  sale_amazon  stock_barcode  industry_fsm  social
voip  iot_drivers  iot_box_image  payment_sepa_direct_debit  web_mobile
```

> 对当前个人学习场景，以上均非刚需。

---

## 六、用户与权限

- **教师**：`tutoring_center.group_teacher`（权限类别"R3ynA 学习平台"），对九个业务模型全权，`admin` 已在该组。新建教师账号勾选该组即可。
- **显示全部应用菜单**：`tutoring_center.group_show_hidden_apps`，勾选后恢复被隐藏的应用根菜单（应用/讨论/项目/邮件营销/调查/员工/仪表板）。
- **门户**：`base.group_portal` 对业务模型只读；record rule 限定只能读取 `partner_id` 等于自己的学生档案及其课次/考试/错题/知识点掌握（跨学生访问 404）。不开放自助注册；账号在学生表单 →"门户账号"联系人上设置（本机无 SMTP，初始密码直接在用户表单填）。
- 超管 `admin` 属 `base.group_system`，可修改一切。

---

## 七、开发者模式（改配置 / 看技术表必需）

- URL 后加 **`?debug=1`**，或 设置页拉到底点 **「激活开发者模式」**。
- 开启后齿轮菜单出现 **Technical（技术）**：模型、字段、视图、自动化规则、**系统参数（`ir.config_parameter`）**、计划任务（cron）、日志。

---

## 八、日常运维

### 服务控制（使用技能脚本，勿手搓）

> 该 skill 的完整说明——action/target 全表、**UAC 提权与超时规则**、六层 `check` 明细、失败判读、红线——见 [service-control.md](service-control.md)；
> 仓库内另存脚本副本 `.agent/scripts/svcctl.ps1`（换机或 skill 丢失时用）。

```bash
powershell -NoProfile -ExecutionPolicy Bypass -File \
  "%USERPROFILE%\.qoder-cn\skills\odoo-service-control\scripts\svcctl.ps1" <action> <target> [lines]
```

| action | target | 需要管理员 | 说明 |
|---|---|---|---|
| `status` | `odoo` / `pg` / `all` | 否 | 服务状态、启动类型、5432/8069 归属进程 |
| `check` | — | 否 | 六层体检（见下） |
| `start` | `odoo` / `pg` / `all` | **是（弹 UAC）** | 启动并等待 `Running` |
| `stop` | 同上 | **是（弹 UAC）** | 强制停止并等待 `Stopped` |
| `restart` | 同上 | **是（弹 UAC）** | 重启并等待恢复 |
| `logs` | `odoo` / `pg` | 否 | 日志尾部，`[lines]` 默认 30、最大 500 |

- `all` 的顺序：**启动** PG→Odoo；**停止** Odoo→PG。
- 改完 `odoo.conf` 用 `restart odoo`，不要动 PostgreSQL。
- **不要仅凭服务状态判断可用**——Odoo 可能 `Running` 却连不上库，务必用 `check` 复核。

`check` 校验六层：
服务状态 → 端口/归属进程 → `odoo.conf` 的 `db_user`/`db_password`/`db_template` → 用该凭据真实登录 `psql` → 每个库的 `datcollate` vs `datctype` → HTTP `/web/database/list` → **限定在本次进程启动时间窗内**的 odoo.log 错误行。

### tutoring_center 模块升级（两种方式，按变更类型选择）

```bash
# 方式一：改了 Python 代码（新增模型/字段/控制器）——必须重启服务
powershell ... svcctl.ps1 stop odoo     # UAC
"E:\Odoo\python\python.exe" "E:\Odoo\server\odoo-bin" -c "E:\Odoo\server\odoo.conf" \
  -d OdooForDB -u tutoring_center --stop-after-init
powershell ... svcctl.ps1 start odoo    # UAC

# 方式二：仅 XML 视图/数据/既有字段 schema 变更——服务运行中就地升级，免重启免 UAC
"E:\Odoo\python\python.exe" "E:\Odoo\server\odoo-bin" shell -c "E:\Odoo\server\odoo.conf" \
  -d OdooForDB < "E:\Odoo\dev\upgrade_via_rpc.py"
```

- 判断标准：**运行中的服务无法加载新增的 Python 模型类/控制器**（sys.modules 缓存）；方式二完成就地升级后经数据库 signaling 自动通知运行中服务重载，无需重启。
- 新建存储型计算字段（stored compute）时尤其注意：服务运行中直接就地升级可能因列未创建而报错，走方式一最稳。

### 测试与演示脚本（`E:\Odoo\dev\`）

| 脚本 | 用途 |
|---|---|
| `make_qa_user.py` / `del_qa_user.py` | 创建/删除临时教师验收账号（qa_check / QaCheck@2026），**用完即删** |
| `upgrade_via_rpc.py` | 进程内升级 tutoring_center |
| `seed_knowledge.py` / `seed_data.py` | 演示知识点 / 学生样例数据 |

### 服务与路径

| 项目 | 值 |
|---|---|
| 服务 | `odoo-server-19.0`（nssm 包装，以 `LocalSystem` 运行，工作目录 `E:\Odoo\python`）<br>`postgresql-x64-18`（程序 `D:\PostSQL`，数据 `D:\PostSQL\data`） |
| Odoo 配置 | `E:\Odoo\server\odoo.conf` |
| Odoo 日志 | `E:\Odoo\server\odoo.log`（**时间戳为 UTC，本地 = UTC+8**） |
| 数据目录 | `%LOCALAPPDATA%\OpenERP S.A\Odoo` |
| **会话文件** | 数据目录 `\sessions\`——清空即让所有浏览器登出（排查残留会话 403 用） |
| `psql.exe` | `D:\PostSQL\bin\psql.exe`（**不在 PATH**；Odoo 19 中多数字段为 jsonb，查询用 `name->>'zh_CN'`） |
| 业务库角色 | `openpg`（LOGIN + CREATEDB，非超级用户） |
| 本地凭据 | `odoo.conf` 的 `db_password`；`%USERPROFILE%\odoo-credentials.txt`（**勿提交仓库、勿贴聊天记录**） |

### 备份 / 恢复

- **逻辑备份 = 数据库 + filestore，两者缺一不可**：
  - 数据库：`pg_dump OdooForDB`
  - 附件/图片：`%LOCALAPPDATA%\OpenERP S.A\Odoo\filestore\OdooForDB`
- 图形化：数据库管理器页 → `Backup`（生成含 filestore 的 zip）/ `Restore`。该页由 `admin_passwd` 保护。
- 2026-09-29 改造前全量备份在 `E:\Odoo\backup\`。

---

## 九、本机已知陷阱

### 数据库 / 服务类

1. **`db_template = odoo_template_c`（C/C）不可改回 `template0`**
   Windows 上 PostgreSQL 拒绝连接 collate≠ctype 的数据库。
   **已存在库的排序规则无法修改**，只能删库重建。
   → 症状：`check` 第 4 节报 `<db>|C|English_United States.936`。

2. **Odoo 以 `LocalSystem` 运行**——用户目录下的 `pgpass.conf` 它读不到，
   数据库密码**必须**写在 `odoo.conf` 的 `db_password`，否则报 `fe_sendauth: no password supplied`。

3. **日志时区不一致**——odoo.log 为 UTC，PostgreSQL 日志为 CST，跨日志关联需换算（本地 UTC+8）。

4. **8069 监听 0.0.0.0**——局域网可达，`admin_passwd` 与 `admin` 口令不要用弱密码。

### Odoo 19 开发类

5. **表单 chatter 必须写 `<chatter/>`**——旧式 `<div class="oe_chatter">` 塞 `message_follower_ids` 等字段会被当成普通子列表渲染成 CRM 风格的三张表（跟进者/活动/消息）。

6. **`_sql_constraints` 已弃用**——用类属性 `models.Constraint('unique(...)', '错误消息')`。

7. **自定义默认视图 priority 必须为 0**——`base.view_partner_form` 等核心视图 priority=1，同为 1 时按视图 id 排序、老视图胜出（表现为"改了视图但某些入口还是老样子"）。

8. **按 xpath 改他人模块视图时，DB 里的 arch 是翻译后的中文**——不要按英文文本匹配（如卡片标题 "Addresses"），应匹配翻译无关的属性（如卡片 `t-set="url"` 的 `t-value`），否则运行时 500：`上级视图内找不到元素`。

9. **删除他人模块记录的 `<delete>` 是一次性操作**——生效后应从自己模块 XML 中移除该行，否则每次升级告警 `Skipping deletion for missing XML ID`。

10. **升级 project / contacts / portal 等原模块会复位界面定制**——项目门户卡片、联系人动作视图指向、应用菜单绑定可能复活；重跑一次 `tutoring_center` 升级即恢复。

### 会话 / 测试类

11. **删除测试账号后，其残留会话 cookie 会导致浏览器 403**（"不允许访问 Website 记录"）——清空 `sessions\` 目录，或换主机名（127.0.0.1 / localhost / 127.0.0.2）隔离 cookie 继续测试。

12. **列表里的「模块」多数不是业务应用**——技术模块随依赖自动带入；只有 `application = true` 的才是真正的「应用」。

---

## 十、快速自查清单

```bash
# 1. 服务与端口
powershell ... svcctl.ps1 status all

# 2. 六层完整体检（服务状态不足以说明可用）
powershell ... svcctl.ps1 check

# 3. 出问题看日志（注意 UTC）
powershell ... svcctl.ps1 logs odoo 80
```

| 症状 | 原因 / 下一步 |
|---|---|
| `db_password set: NO` / `fe_sendauth: no password supplied` | Odoo 无可用凭据 → 在 `odoo.conf` 设 `db_password` 后 `restart odoo` |
| `check` 第 4 节 collate/ctype 不匹配 | 见陷阱 1，需删库用 `odoo_template_c` 重建 |
| 打开学生/联系人表单出现"跟进者/活动/消息"三张表 | 表单用了旧式 chatter 写法 → 改 `<chatter/>` 后升级模块（陷阱 5） |
| 某入口打开的还是老版表单 | 自定义视图 priority 丢失 → 检查 `partner_views.xml` 的 priority=0（陷阱 7） |
| `/my` 打开 500，日志报"上级视图内找不到元素" | portal 首页 xpath 失配 → 检查 `portal_templates.xml` 卡片删除的 xpath（陷阱 8） |
| 浏览器 403"不允许访问 Website 记录" | 残留会话 → 清空 `sessions\` 目录（陷阱 11） |
| 界面定制突然复活（项目卡片/应用菜单等） | 原模块被升级复位 → 重跑 `tutoring_center` 升级（陷阱 10） |
| 5432 正常但第 5 节 HTTP 失败 | Odoo 起了但数据层坏 → 看第 6 节与 `logs odoo 80` |
| 服务 `Running` 但 8069 未监听 | Odoo 正在启动或崩溃重启中 → `logs odoo 60` |
| 报 `service not installed` | 服务被卸载或改名 → 用 `Get-Service` 确认 |
