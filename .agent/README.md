# Odoo 19 本机操作说明

> 环境：Windows + Odoo 19 **Community（社区版）** + PostgreSQL 18，安装于 `E:\Odoo`。
> 本文所有事实均取自本机实测（2026-09-29）。改配置前请先读完第九节「坑」。

---

## 一、访问与登录

| 项目 | 值 |
|---|---|
| 地址 | http://127.0.0.1:8069 |
| 局域网访问 | `http_interface = 0.0.0.0`，可用 `http://<本机IP>:8069` |
| 数据库管理器 | http://127.0.0.1:8069/web/database/manager |
| 管理员密码 | `odoo.conf` 中 `admin_passwd` 原值（用于创建/备份/恢复/删除数据库） |
| 业务库 | `OdooForDB` |
| 登录账号 | `admin`（超管）。当前共 4 个用户：`admin`、`__system__`(OdooBot 机器人)、`public`、`portaltemplate` |
| 语言 / 数据 | 中文 `zh_CN`，`with_demo = False`（无演示数据，空账套） |

登录后右上角 **齿轮图标** 为主菜单：应用、设置、用户、技术（仅开发者模式可见）。

---

## 二、界面三大入口

1. **Apps（应用）** —— 安装/卸载模块。
2. **Settings（设置）** —— 公司信息、用户与权限、翻译、技术参数。
3. **各业务应用菜单** —— 安装了什么就出现什么。

---

## 三、当前已装能力（68 个模块）

| 已装应用 | 功能 |
|---|---|
| **Project 项目** | 任务、看板、甘特、工时；含 `project_todo` 待办 |
| **Website 建站** | 拖拽建站、页面、主题（`theme_bewise` / `theme_common`）、表单 |
| **Contacts 联系人** | 客户/供应商/公司主数据 |
| **Employees 员工** | `hr`、`hr_org_chart`（组织架构）、`hr_homeworking`（远程办公）、`hr_skills`（技能） |
| **Survey 问卷** | 调查/测验，可挂到网站 |
| **Email Marketing** | `mass_mailing` + 邮件主题模板 |
| **SMS / Snailmail** | 短信（需 `iap` 额度）、纸质信函 |
| **Discuss 讨论** | `mail`、`bus`，所有单据自带沟通记录 |
| **Portal 门户** | 外部客户登录查看单据 |
| **安全** | `auth_totp`（双因素）、`auth_passkey`（通行密钥）、`auth_signup` |
| **平台类** | `base`、`web`、`analytic`（分析会计）、`uom`（计量单位）、`digest`（周期摘要）、`gamification`（游戏化激励） |

> 定位：**「项目 + 官网 + 人事 + 问卷营销」**，**尚未安装任何财务 / 进销存 / 生产模块**。

模块统计（`ir_module_module`）：

| state | 数量 | 含义 |
|---|---|---|
| `installed` | 68 | 已启用 |
| `uninstalled` | 622 | 可安装，代码在本机（其中 25 个是完整「应用」`application=true`） |
| `uninstallable` | 23 | 代码缺失（企业版），装不了 |

---

## 四、如何启用更多应用（离线，无需下载）

1. Apps 页搜索模块名 → 点 **启用 / Activate** → 等待安装完成（数秒~数分钟）。
2. 列表里找不到模块 → 点 Apps 页顶部 **「更新应用列表 / Update Apps List」** 重扫 `addons` 目录。

本机 `addons_path = e:\odoo\server\odoo\addons`（692 个模块目录），**已确认磁盘上存在**的常用业务模块：

| 模块 | 用途 |
|---|---|
| `account` | **Invoicing 开票 / 基础会计**（账单、发票、税务） |
| `sale_management` | 销售订单、报价、价格表 |
| `purchase` | 采购订单 |
| `stock` | 库存、出入库、仓库、批次/序列号 |
| `mrp` + `mrp_account` | **制造**：BOM、工艺路线、工单、成本核算 |
| `website_sale` | 网店（对接销售 + 库存） |
| `point_of_sale` | POS 零售收银 |
| `hr_expense` | 员工报销 |
| `maintenance` | 设备维护保养 |
| `fleet` | 车辆管理 |
| `repair` | 维修工单 |

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

> **制造业质量方向注意**：社区版 `mrp` 仅有工单/BOM/工作中心；
> **质检点、质检单、车间平板报工（`quality*`、`mrp_workorder`）均为企业版**。
> 若为刚需：上 Enterprise，或使用 OCA 社区替代模块（需自行下载 zip 放入 `addons` 目录）。
> 同理，`account` 是基础开票，完整「会计」（银行对账等，`account_accountant`）也是企业版。

---

## 六、用户与权限

- **设置 → 用户 → 新建**：填姓名/邮箱，授权组决定可见菜单。
- 常用组：`Settings`（管理员）、`Sales`、`Inventory`、`Accounting`、`Project`、`Portal`（外部）、`Public`（匿名）。
- 超管 `admin` 属 `base.group_system`，可修改一切。

---

## 七、开发者模式（改配置 / 看技术表必需）

- URL 后加 **`?debug=1`**，或 设置页拉到底点 **「激活开发者模式」**。
- 开启后齿轮菜单出现 **Technical（技术）**：模型、字段、自动化规则、**系统参数（`ir.config_parameter`）**、计划任务（cron）、日志。

---

## 八、日常运维

### 服务控制（使用技能脚本，勿手搓）

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

### 服务与路径

| 项目 | 值 |
|---|---|
| 服务 | `odoo-server-19.0`（nssm 包装，以 `LocalSystem` 运行，工作目录 `E:\Odoo\python`）<br>`postgresql-x64-18`（程序 `D:\PostSQL`，数据 `D:\PostSQL\data`） |
| Odoo 配置 | `E:\Odoo\server\odoo.conf` |
| Odoo 日志 | `E:\Odoo\server\odoo.log`（**时间戳为 UTC，本地 = UTC+8**） |
| 数据目录 | `%LOCALAPPDATA%\OpenERP S.A.\Odoo`（即 `C:\Users\<用户名>\AppData\Local\...`） |
| `psql.exe` | `D:\PostSQL\bin\psql.exe`（**不在 PATH**） |
| 业务库角色 | `openpg`（LOGIN + CREATEDB，非超级用户） |
| 本地凭据 | `odoo.conf` 的 `db_password`；`%USERPROFILE%\odoo-credentials.txt`（**勿提交仓库、勿贴聊天记录**） |

### 备份 / 恢复

- **逻辑备份 = 数据库 + filestore，两者缺一不可**：
  - 数据库：`pg_dump OdooForDB`
  - 附件/图片：`%LOCALAPPDATA%\OpenERP S.A.\Odoo\filestore\OdooForDB`
- 图形化：数据库管理器页 → `Backup`（生成含 filestore 的 zip）/ `Restore`。该页由 `admin_passwd` 保护。

---

## 九、本机已知陷阱

1. **`db_template = odoo_template_c`（C/C）不可改回 `template0`**
   Windows 上 PostgreSQL 拒绝连接 collate≠ctype 的数据库，Odoo 在 `db_template=template0` 时会建出该形状的库。
   模板须为纯 C 的 `odoo_template_c`（属主 `openpg`，PG 无 `TEMPLATE` 权限故须属主授予）。
   **已存在库的排序规则无法修改**，只能删库重建。
   → 症状：`check` 第 4 节报 `<db>|C|English_United States.936`。

2. **Odoo 以 `LocalSystem` 运行**——用户目录下的 `pgpass.conf` 它读不到，
   数据库密码**必须**写在 `odoo.conf` 的 `db_password`，否则报 `fe_sendauth: no password supplied`。

3. **日志时区不一致**——odoo.log 为 UTC，PostgreSQL 日志为 CST，跨日志关联需换算（本地 UTC+8）。

4. **8069 监听 0.0.0.0**——局域网可达，`admin_passwd` 与 `admin` 口令不要用弱密码。

5. **无演示数据**（`with_demo = False`），但 `default_productivity_apps = True`，
   新建数据库会自动预装项目/官网一类生产力应用。

6. **列表里的「模块」多数不是业务应用**——技术模块会在安装业务应用时被依赖自动带入，
   无需手动启用；只有 `application = true` 的才是真正的「应用」。

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
| 5432 正常但第 5 节 HTTP 失败 | Odoo 起了但数据层坏 → 看第 6 节与 `logs odoo 80` |
| 服务 `Running` 但 8069 未监听 | Odoo 正在启动或崩溃重启中 → `logs odoo 60` |
| 报 `service not installed` | 服务被卸载或改名 → 用 `Get-Service` 确认 |
