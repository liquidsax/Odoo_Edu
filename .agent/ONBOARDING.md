# 协作者安装配置指南（面向 agent）

> 目标读者：接手本项目的协作者及其 agent。
> 读完本文档应能：从零装好完整环境 → 初始化项目 → 自检通过 → 进入开发工作流。
> 项目背景速览见 [handoff.md](handoff.md)，面向人的总览见仓库根 [README.md](../README.md)。

---

## 路径选择

- **路径 A：原生 Windows 安装（优先）**——与维护者环境同构（Odoo 19 社区版 + PostgreSQL 18），下方完整交代；
- **路径 B：Docker**（备选，步骤最少但依赖容器技术，调试Odoo本身时不如原生直接）。

两条路径产出的环境等价，数据互不相通。**不要同时混用**（尤其不要让原生 Odoo 和容器 Odoo 共用同一数据库）。

---

## 路径 A：原生 Windows 安装（推荐，完整步骤）

### A0. 前置条件

| 组件 | 版本/要求 | 说明 |
|---|---|---|
| Windows | 10/11 或 Server | 维护者环境为 Windows 10+ x64 |
| Git | 任意近期版本 | 含 Git Bash（运行脚本需要） |
| PostgreSQL | **18** | EDB 官方安装包，安装时记住超级用户 postgres 密码 |
| Python | **3.12**（3.10+ 可用，维护者实测 3.12） | 安装时勾选 "Add to PATH" |
| 磁盘 | ≥ 5 GB | Odoo 源码 + 依赖 + 数据 |

不需要安装：Node.js（本项目不用 RTL 语言）、wkhtmltopdf（未启用 PDF 报表）、LibreOffice（仅维护者做 PPT 质检用）。

### A1. 安装 PostgreSQL 18 并建 Odoo 角色与模板库

1. 运行 EDB 安装包（默认端口 5432），记住 postgres 密码；
2. 打开 SQL Shell（psql，以 postgres 登录），执行——**以下顺序和写法是维护者实测结论，不要省略任何一步**：

```sql
-- 1) Odoo 专用登录角色（CREATEDB 用于建库；名字与密码自定，下文以 openpg 为例）
CREATE ROLE openpg LOGIN PASSWORD '<自定强密码>' CREATEDB;

-- 2) 建纯 C 排序规则的模板库
CREATE DATABASE odoo_template_c
    ENCODING 'C' LC_COLLATE 'C' LC_CTYPE 'C' TEMPLATE template0;

-- 3) 把模板库属主改为 openpg（PostgreSQL 没有 TEMPLATE 权限，
--    Odoo 以 openpg 身份 WITH TEMPLATE 建库时要求它是模板属主）
ALTER DATABASE odoo_template_c OWNER TO openpg;
```

> ⚠️ **本步骤是 Windows 上最大的坑**：Odoo 默认 `db_template = template0`，在 Windows 上会建出
> collate ≠ ctype 的库，之后 PostgreSQL 直接拒绝连接（症状：日志报 `<库名>|C|English_United States.936`）。
> 必须用上面的 `odoo_template_c` 并在 odoo.conf 里指定（见 A4）。**已存在库的排序规则无法修改**，错了只能删库重来。

### A2. 获取 Odoo 19 社区版源码并装 Python 依赖

```bat
git clone -b 19.0 --depth 1 https://github.com/odoo/odoo.git E:\odoo19
py -3.12 -m venv E:\odoo19\venv
E:\odoo19\venv\Scripts\pip install -r E:\odoo19\requirements.txt
```

源码位置可自定（下文以 `E:\odoo19` 为例，**后面 odoo.conf 里的路径要与之一致**）。

> **不要改 Odoo 本体源码**：本项目所有内容都放在自研模块 `server/addons/tutoring_center` 里，
> 维护者本机的源码树自 2026-09-21 装好后**零改动**（已核实），所以直接 clone 上游 19.0 即可，
> 仓库不带源码不会丢东西。若确需改本体，请先与维护者商量——那些改动进不了 git，换机即失效。

### A3. 克隆本项目仓库

```bat
git clone https://github.com/liquidsax/Odoo_Edu.git E:\Odoo_Edu
cd E:\Odoo_Edu && git checkout main && git pull
```

**addons_path 直接指向仓库内的 `server\addons` 目录**——这样自定义模块始终在 git 工作区里，改完代码即改完"线上"代码，热重载所见即所改。

### A4. 编写 odoo.conf（放在仓库根目录或 Odoo 源码目录均可）

仓库根有脱敏模板 `odoo.conf.example`，直接复制成 `odoo.conf` 再填密码与路径即可：

```bat
copy odoo.conf.example odoo.conf
```

内容要点（与模板一致）：

```ini
[options]
admin_passwd = <自定强密码，仅数据库管理器页面用>
db_host = 127.0.0.1
db_port = 5432
db_user = openpg
db_password = <A1 中给 openpg 设置的密码>
db_template = odoo_template_c
addons_path = E:\odoo19\odoo\addons,E:\odoo19\addons,E:\Odoo_Edu\server\addons
http_interface = 127.0.0.1
; 开发期日志走控制台（不设 logfile），便于看热重载输出
```

> 仓库卫生：`odoo.conf` 含密码，**已在 .gitignore 中排除，永远不要提交**（或提交一份 `odoo.conf.example` 脱敏版）。
> 默认只监听 127.0.0.1；确需局域网访问再改 `0.0.0.0`，并同步提升 admin_passwd 与口令强度。

### A5. 初始化数据库并安装本项目模块

```bat
E:\odoo19\venv\Scripts\python E:\odoo19\odoo-bin -c E:\Odoo_Edu\odoo.conf ^
    -d edu_native -i tutoring_center --load-language=zh_CN --without-demo=all --stop-after-init
```

成功判据：进程正常退出、末尾无 ERROR，数据库 `edu_native` 已建且模块已装。

> `contacts`（联系人应用）会随 `tutoring_center` 的依赖自动装上，**不要**手动列进 `-i`。
> 2026-09-30 已用全新库实测本步骤：67 个模块安装无 CRITICAL，首页门面、`/my/learning`、
> `/tools/function-plot` 及其 JS/CSS 资产包全部正常。

### A6. 启动、账号与演示数据

```bat
:: 开发期用控制台前台运行（Ctrl+C 停止），不要先注册成服务
E:\odoo19\venv\Scripts\python E:\odoo19\odoo-bin -c E:\Odoo_Edu\odoo.conf
```

- 教师后台 http://127.0.0.1:8069/web/login ，首次 `admin` / `admin`，**登录后立即改密**；
- 演示数据（可选，在 Git Bash 中执行）：

```bash
E:/odoo19/venv/Scripts/python E:/odoo19/odoo-bin shell -c E:/Odoo_Edu/odoo.conf -d edu_native < dev/seed_knowledge.py
E:/odoo19/venv/Scripts/python E:/odoo19/odoo-bin shell -c E:/Odoo_Edu/odoo.conf -d edu_native < dev/seed_data.py
```

门户账号密码用环境变量注入：`TUTOR_DEMO_PW_A=xxx TUTOR_DEMO_PW_B=yyy python odoo-bin shell ... < dev/seed_data.py`。

品牌装饰（可选，想让站点和维护者看到的一模一样时才跑）。公司名/站点名/logo/页脚不在模块 data 里，
是一次性写库的脚本，按顺序执行（脚本无密码、无绝对路径依赖，可重复跑）：

```bash
E:/odoo19/venv/Scripts/python E:/odoo19/odoo-bin shell -c E:/Odoo_Edu/odoo.conf -d edu_native < dev/branding.py    # 公司名 / 站点名
E:/odoo19/venv/Scripts/python E:/odoo19/odoo-bin shell -c E:/Odoo_Edu/odoo.conf -d edu_native < dev/branding2.py   # 页脚与版权行
E:/odoo19/venv/Scripts/python E:/odoo19/odoo-bin shell -c E:/Odoo_Edu/odoo.conf -d edu_native < dev/branding3.py   # LOGO（内联 SVG）/ 隐藏标题文本
```

### A7. 开发热重载（边改边看）

以控制台方式运行（A6），并给启动命令加 dev 参数：

```bat
E:\odoo19\venv\Scripts\python E:\odoo19\odoo-bin -c E:\Odoo_Edu\odoo.conf --dev=xml,qweb,reload
```

| 改什么 | 生效方式 |
|---|---|
| 视图 / 数据 XML | 保存后**刷新浏览器** |
| QWeb 模板（`views/*.xml` 里的模板） | 同上 |
| 前端 JS / CSS（`static/src`） | **打包模式下刷新无效**：需 `-u tutoring_center --stop-after-init` 重建资产包；启动时带 `--dev=assets` 则直接读源文件、刷新即可 |
| Python 模型 / 控制器 | 控制台 Ctrl+C 后重新运行（改模型类/控制器必须重启；纯字段/视图变更可免） |
| `__manifest__.py`、新增字段后视图报错 | 手动升级：`-u tutoring_center --stop-after-init` 后再启动 |

（可选）长期运行再考虑注册 Windows 服务（维护者用 nssm 包装，见根 README「服务与路径」）；开发期一律前台运行。

### A8. 原生环境常见问题

| 症状 | 原因 / 处理 |
|---|---|
| 日志报 `fe_sendauth: no password supplied` | odoo.conf 没写 `db_password`，或以服务方式运行导致读不到 pgpass——密码必须写在 odoo.conf |
| `check`/日志报 `<库>\|C\|English_United States.936` | 踩了 A1 的模板坑，删库按 A1 重建 |
| 8069 被占用 | 换 `http_port = 18069` |
| pip 装 requirements 失败 | 确认 Python 3.10~3.12；个别包缺 wheel 时升级 pip 后重试 |
| 日志报 `The ID "xxx.yyy" refers to an uninstalled module` | 自研模块用了他人模块的记录却没声明依赖 → 补进 `__manifest__.py` 的 `depends`（纯展示性/清理性的引用改用容错 `<function>`，见 `models/ir_ui_view.py`） |
| 界面是英文 | 初始化时漏了 `--load-language=zh_CN`，后台 Settings → Translations 手动加载 |
| 改了 Python 没生效 | 模型类/控制器变更必须重启进程（见 A7 表） |

---

## 路径 B：Docker（备选，步骤最少）

前提：Docker Engine / Docker Desktop（Windows 需 WSL2 后端）。

```bash
git clone https://github.com/liquidsax/Odoo_Edu.git && cd Odoo_Edu
docker compose up -d        # 自动建库 + 装 tutoring_center + 中文语言包
./dev/seed_docker.sh        # 演示数据（可选）
```

- 打开 http://localhost:8069（`admin`/`admin`，立即改密）；
- compose 已带 `--dev=xml,qweb,reload`，模块源码直挂容器，热重载规则同 A7（Python 改动容器自动重启）；
- 手动升级：`docker compose exec odoo odoo -d edu_dev --db_host=db --db_user=odoo --db_password=odoo -u tutoring_center --stop-after-init` 后 `docker compose restart odoo`；
- 清空重来：`docker compose down -v`（容器内数据一次性，不影响仓库代码）；
- 8069 占用改端口映射；详细说明见根 README「快速开始」。

> **PG18 挂载点（2026-10-01 修正）**：`postgres:18-alpine` 的数据卷必须挂在 `/var/lib/postgresql`，
> 挂成 `.../data` 会被 entrypoint 判为脏卷并无限重启——即本文件路径 B 在此之前**在任何机器上都起不来**。
> 在此之前 clone 的旧副本要 `docker compose down -v` 重来一次。
>
> **要部署到公网服务器**：不要直接拿本节的开发配置对外提供服务——至少去掉 `--dev`（开发单进程服务器会把
> 堆栈渲染进页面）、设 `list_db = False`、改掉建库自带的 `admin/admin`、限制容器内存。
> 我们那台云机的具体配置（地址、目录、口令位置）记在**仓库外的本地笔记**里，不进开源仓库；
> 通用踩坑见 `updates/2026-10-01.md` 的"云端部署踩坑"。

---

## 环境自检清单（agent 逐项验证后再开始开发）

1. 服务进程正常（原生：控制台无 ERROR 且 8069 监听；Docker：`docker compose ps` 均 running/healthy）；
2. http://127.0.0.1:8069/ 打开为"数学辅导 · 学习数据平台"门面，导航含"学习平台"；
3. admin 登录后台：顶栏菜单只有 **数学辅导（学生 / 知识点）** 与 联系人、网站；
4. 学生列表打开正常；任选学生进表单，页签（知识点掌握/学校考试/辅导课次/错题记录）渲染正常；
5. （灌过演示数据后）门户账号登录 `/my` 自动跳转 `/my/learning`，统计卡与折线图正常绘制；
6. 热重载验证：改 `views/tutoring_views.xml` 任一字符串保存 → 刷新浏览器可见变化。
7. 顶栏第三项「函数图像」打开正常：点「椭圆」填分母 5 和 1 → 出 `x^2/5+y^2=1`；点「双曲线」切「系数式」默认值即 `x^2-4y^2=4`（顶点 ±2，两支之间不连线）；点「直线」填 A=1、B=-2、C=-4 → 出 `x-2y-4=0`；`x^2+y^2=4` 必须是**正圆**（两轴等比例）；`y=1/x` 两条分支断开不连线；滚轮缩放、拖动平移、右上角全屏按钮能铺满窗口。

---

## 开发工作流（务必遵守）

1. **开工前**：`git checkout main && git pull`；
2. **新建分支**：`feature/<主题>`（新功能）或 `fix/<主题>`（修复），如 `feature/exam-chart`、`fix/portal-403`；
3. **提交**：信息用中文，说明"改了什么、为什么"；保持仓库卫生——不提交真实密码、凭据、`odoo.conf`、备份、学生真实数据，不硬编码本机绝对路径；
4. **收尾**：push 自己的分支 → 开 Pull Request → **由管理员（liquidsax）审查后合并**；禁止直接向 `main` 推送。
