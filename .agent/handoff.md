# 工作交接（handoff）

> 记录开始：2026-09-29。本文件只保留**最新且最重要**的信息；
> 完整演进详情按日期记录在 [updates/](updates/) 目录，安装配置见 [ONBOARDING.md](ONBOARDING.md)。

---

## ⚠️ 协作规则（所有协作者 / agent 动手前必读）

1. **开始修改代码之前，先拉取最新代码**：`git checkout main && git pull`；
2. **禁止直接向 `main` 分支推送**：所有修改在**新建分支**上进行——
   - 新功能：`feature/<主题>`（如 `feature/exam-chart`）
   - 问题修复：`fix/<主题>`（如 `fix/portal-403`）
3. 提交信息用中文，说明"改了什么、为什么"；
4. 完成后 push 自己的分支并开 **Pull Request**，由**管理员（liquidsax）审查后合并**；
5. **仓库卫生红线**：不提交真实密码 / 数据库凭据 / `odoo.conf` / 数据库备份 / 学生真实数据 / 截图素材；不硬编码本机绝对路径（用相对路径，文档中用 `%USERPROFILE%` / `%LOCALAPPDATA%` 写法）；
6. 密码类参数一律走环境变量注入（参考 `dev/seed_data.py` 的 `TUTOR_DEMO_PW_A/B`）。

## 一、项目定位

本机 Odoo 19 社区版（业务库 `OdooForDB`）已改造为**数学辅导数据中台**（一对一个性化数学辅导）：

- 教师端（`admin` 后台）维护学生、知识点、辅导课次、学校考试成绩、错题记录；
- 学生/家长端（portal）在 `/my/learning` 查看学习数据，多学生按门户联系人硬隔离；
- 辅导模式为**纯讲题 120 分钟/节**：不布置作业、不布置在线考试（仅录入在校考试成绩）；作业模型保留但已全面退出界面；
- 网站首页为教育门面，无 ERP/CRM 入口；
- 网站顶栏第三项「函数图像」（`/tools/function-plot`，公开页面）：按曲线类型填题目里的参数自动成图（椭圆/双曲线有「分母式」与「系数式」两种填法），也能自己写方程；预览与图例按数学写法渲染（`prettyEquation()`，上标/π/去括号）；支持缩放平移、悬停读数、画布全屏；纯前端计算、零第三方依赖。

- **错题记录**（学生不会/做错的题）：来源关联**练习册**（可填页码/题号）、**辣椒难度 2~5 🌶**、系统自动的**记录时刻**＋可手填「发生日期」、可选「错因/备注」——**不记题目内容**（不通过平台做题，只记错了哪道题）；**不设订正状态**（这页只用于记录出处，没人会做完一道题再回网站改状态）。后台列表控制栏有常驻「**快速记录**」弹窗：题号可写 `1-5`、`1,3,7` 自动拆成多条，「保存并继续」沿用学生/练习册只清出处；列表为 **Excel 式可编辑网格**，新建行自动沿用上一条的学生与练习册，难度**点辣椒即改**（`chili` 组件，列表未进入编辑态也可点）；门户有错题列表/详情，**学生可自助添加/编辑自己的错题**（记录规则强制只能本人、不可删）。

核心自定义模块：`server/addons/tutoring_center`（11 个模型，含练习册 `tutoring.workbook` 与速记向导 `tutoring.mistake.quickadd`，详见根 README）。

## 二、环境与使用方式

| 角色 | 环境 | 说明 |
|---|---|---|
| **协作者** | 原生 Windows 安装（**优先**） | PostgreSQL 18 + Python 3.12 + Odoo 19 源码，完整步骤见 [ONBOARDING.md](ONBOARDING.md) 路径 A |
| **协作者（备选）** | Docker（`docker compose up -d`） | ONBOARDING.md 路径 B，容器内 `edu_dev` 库，数据一次性 |
| **维护者** | 原生 Windows 服务 | Odoo 19 社区版 + PostgreSQL 18（服务 `odoo-server-19.0` / `postgresql-x64-18`），**本机不装 Docker** |

两套环境数据完全隔离。维护者环境的详细安装/陷阱见根 README 与 `updates/2026-09-29.md`。

## 三、当前数据与账号（维护者本机）

| 对象 | 事实 |
|---|---|
| 学生"表弟"（id 2） | 初一，已**结课**；5 次课、2 场考试（78%/85%）、3 条掌握、2 条错题（演示） |
| 学生"小明"（id 4） | 初一，**真实数据**，总课次 20 |
| 学生"示例学生B"（id 3） | 初二，隔离验证用，可删 |
| portal 账号 | `biaodi`（表弟）、`student02`（示例学生B）；密码见本地密码记录，**不入库** |
| 知识点 | 初一 5 个演示数据 |
| 练习册 | 仅默认「课内/其他」(id 1)——升级时把存量 2 条错题回填于此；真实练习册（五年模拟三年高考等）待维护者录入 |

容器演示环境的账号由 `dev/seed_data.py` 创建（`biaodi` / `student02`，密码环境变量注入）。

## 四、维护者高频操作要点

> 服务启停与体检**统一走 Qoder skill `odoo-service-control` 的 `svcctl.ps1`**（命令、UAC 规则、六层 `check`、失败判读见 [service-control.md](service-control.md)），不要手搓 `Start-Service` / `Stop-Service`。

1. **标准升级**（Python 变更必须走）：`svcctl.ps1 stop odoo`（UAC）→ `"E:\Odoo\python\python.exe" "E:\Odoo\server\odoo-bin" -c odoo.conf -d OdooForDB -u tutoring_center --stop-after-init` → `start odoo`。
2. **纯 XML/数据变更免重启**：`odoo-bin shell -c odoo.conf -d OdooForDB < E:\Odoo\dev\upgrade_via_rpc.py`，脚本内 `button_immediate_upgrade()`，运行中服务经 signaling 自动重载。
3. **硬限制**：运行中的服务无法加载新增 Python 模型类/控制器，必须重启；纯字段/视图变更无此限制。
4. **前端资产（`static/src` 的 JS/CSS）改动也走标准升级**：资产包只在模块升级时重建，改完刷新页面看不到变化（实证见 `updates/2026-09-30.md`）。
5. 服务体检：`svcctl.ps1 check` 六层；日志 UTC（本地 UTC+8）。

## 五、最重要陷阱（Top 13，完整版见 README 与 updates）

1. `db_template = odoo_template_c` **不可改回 template0**（Windows 上 collate≠ctype 库无法连接，已存在库只能删库重建）；
2. `_sql_constraints` 在 Odoo 19 已弃用，用 `models.Constraint('unique(...)', '消息')`；
3. chatter 写法：表单内直接 `<chatter/>`，旧式 `oe_chatter` div 会被当普通子列表渲染；
4. 视图优先级：核心视图 `base.view_partner_form` 为 priority=1，自定义默认视图需 **priority=0** 才能稳定胜出；
5. 若单独升级 `project`/`contacts`/`portal`/`base`，门户卡片/联系人视图指回/菜单隐藏可能复位，**重跑 `tutoring_center` 升级即恢复**；
6. 删除账号后残留会话会导致浏览器 403，全量清 `%LOCALAPPDATA%\OpenERP S.A\Odoo\sessions\` 即可；
7. git：`.gitignore` 的 `*` 不匹配点开头文件；且本地 Odoo 源码树 `server/.gitignore` 的否定行已移除（详见 updates，重装 Odoo 源码需重做）；
8. **画布/交互容器上对 `pointerdown` 调 `preventDefault()` 会抑制浏览器合成的 `mousedown`/`click`/`dblclick`**——容器内按钮会彻底点不动（本项目「函数图像」页的全屏/重置按钮就栽在这）。前端交互控件必须**真实点击**验收，脚本里的 `element.click()` 合成事件会掩盖此问题（细节见 `updates/2026-09-30.md`）。
9. **用了别人模块的记录就必须声明依赖，否则只有维护者的库能装**——`<record id="contacts.action_contacts">`、`inherit_id="project.*"` 这类写法在**全新库**上直接报 `The ID "…" refers to an uninstalled module` 并中断安装；维护者的库因为从完整 ERP 演示库改造而来，那些模块本来就装着，所以永远发现不了。纯清理/装饰性的跨模块引用不要写死 XML，用容错函数（`env.ref(..., raise_if_not_found=False)`，见 `models/ir_ui_menu.py`、`models/ir_ui_view.py`）。**每次改模块后要用一次性新库跑一次 `-i tutoring_center` 才算验收**（细节见 `updates/2026-09-30.md`）。
10. **门户 QWeb 表单/分页两个坑**：① 表单取 CSRF 令牌要用 `request.csrf_token()`，裸 `csrf_token()` 未注入上下文会 `KeyError` 直接 500；② 列表分页器写 `<t t-call="portal.pager"/>`（`pager` 走上下文），误用 `<t t-out="pager"/>` 会把 `{'page_count':…}` 字典原样打印到页面底部（错题/课次/作业/考试四处已统一修正）。给已有行的表加**必填**字段时，Odoo 升级只会延迟并降级 NOT NULL 约束（不中断），但要用数据阶段 `<function>` 先回填存量行，收尾约束才干净生效（见 `data/mistake_data.xml`）。
11. **Selection 键值按字符串排序，选项定义顺序不算数**——`_order` 与 `read_group` 分组都按**值**比较，`'10' < '7'`，所以两位数键值会把「高一」排在「初一」之前（知识点页默认按年级分组，正是用户天天看的那一屏）。年级键值已统一**补零**为 `07~12`（见 `models/tutoring_knowledge.py` 的 `GRADE_SELECTION`，学生与知识点共用一份定义）；改键值必须配 `migrations/<版本>/pre-migrate.py` 把存量行一起补零，`19.0.1.2.0` 已处理 `tutoring_student`、`tutoring_knowledge_point`（细节与实测见 `updates/2026-10-01.md`）。
12. **列表控制栏按钮的两个死法**：① 按钮方法上加 `@api.model` 必报 `TypeError: takes 1 positional argument but 2 were given`——`call_kw` **只对带 `@api.model` 的方法跳过 ids**，而 `/web/dataset/call_button` 恒以 `[ids]` 为首个位置参数（空选区是 `[[]]`），于是实际调用成 `method(recs, [])`；② `icon` 只认 `fa-`/`oi-` 前缀（`ViewButton.iconFromString` 把其余一律当图片 `src`），写 `icon="fa fa-magic"` 就是一个破图，正确写法 `icon="fa-magic"`。想在列表页放**常驻**按钮，用 `<header><button name="..." type="object" display="always"/>`（19 原生渲染进 `control-panel-always-buttons` 插槽），不必 patch `web.ListView.Buttons`。
13. **并发时对共享业务库跑 `-u` 会吃掉别人的迁移**：Odoo 执行迁移脚本的区间是 `(ir_module_module.latest_version, 新 manifest 版本]`。两路同时把版本写成 `19.0.1.2.0`、而年级补零迁移挂在 `migrations/19.0.1.2.0/`，本方为验收先升级了 `OdooForDB`，`latest_version` 就越过了那个目录，合并后那次统一升级会**静默跳过**对方的迁移（存量 `'7'/'8'` 不补零 → 新键值 `'07'/'08'` 显示为空、分组乱序）。规则：别人有未合并改动时**不要升级业务库**；必须升级则事后核对 `latest_version`，必要时 `UPDATE` 回退一格（详见 `updates/2026-10-01.md`）。

14. **自定义字段组件的 import 必须写绝对别名**——照抄核心文件里的相对路径（如 `from "../standard_field_props"`）会被 `js_transpiler` 按**你自己的模块**解析成 `@tutoring_center/standard_field_props`，该模块不存在 → 整个组件文件加载失败，页面只留一行 `Missing widget: chili for field of type selection` 的 console 警告并**静默回退成默认 widget**（难度列照样显示 🌶🌶🌶，肉眼看不出差别）。跨模块一律写 `@web/views/fields/standard_field_props`；验收要确认自定义类名（如 `.o_tutoring_chili`）真的出现在 DOM 里，而不是"看起来正常"。另：编译后的资产包是 `ir.attachment` 里的 `web.assets_backend.min.js/.css` 两条缓存，只在收到 assets 失效信号时重建——就地升级 `button_immediate_upgrade()` 会重载 registry 但**不**触发该信号，删掉这两条 attachment 即可让下次请求按磁盘新代码重新生成（纯派生缓存，不用停服）。

## 六、文档索引

| 文档 | 内容 |
|---|---|
| [ONBOARDING.md](ONBOARDING.md) | 协作者安装配置指南（原生 Windows 完整步骤 + Docker 备选 + 自检清单 + 工作流） |
| [service-control.md](service-control.md) | 服务启停与体检 skill（`svcctl.ps1`）：action/target、UAC 规则、六层 `check`、失败判读、红线 |
| [updates/](updates/) | 按日期的完整更新记录（含维护者原生环境详情、验证记录、陷阱全表） |
| 根 [README.md](../README.md) | 面向人的项目总览、模块概览、快速开始 |
| `docs/数学辅导数据中台使用说明.md` | 面向使用者的操作说明 |

## 七、备份与交付物

- 改造前全量备份：`E:\Odoo\backup\`（数据库 dump + filestore，**不入库**）；
- `dev/`：演示数据、品牌、进程内升级、临时验收账号等脚本（密码均环境变量注入）；
- `docs/`：使用说明（PPT 及截图素材不入库，仅本地保存）；
- `odoo.conf.example`：脱敏配置模板，复制成 `odoo.conf` 再填密码（真配置含密码，不入库）。

> **仓库只跟踪自研内容**（模块 + 文档 + 运维脚本，共 50 余个文件），Odoo 本体源码不入库、由协作者
> clone 上游 19.0 获取。这不是缺陷：已核实维护者本机源码树自安装后**零改动**，换机不会缺项目代码。
