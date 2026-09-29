# Odoo_Edu · 数学辅导数据中台

基于 **Odoo 19 社区版**的一对一个性化数学辅导数据平台。

- **教师端**（后台）：维护学生档案、知识点、辅导课次、学校考试成绩、错题记录、知识点掌握度；
- **学生/家长端**（门户）：登录 `/my/learning` 查看上课安排、考试成绩趋势（Chart.js 折线图）、最近错题、知识点掌握度；多学生之间按门户联系人硬隔离；
- **网站首页**：教育平台门面，无任何 ERP/CRM 入口。

辅导模式为**纯讲题 120 分钟/节**：不布置作业、不布置在线考试（考试成绩仅录入学生在校考试）。

## 仓库内容

| 路径 | 内容 |
|---|---|
| `server/addons/tutoring_center/` | 核心自定义模块（application，依赖 `portal`、`website`） |
| `docs/数学辅导数据中台使用说明.md` | 面向使用者的操作说明 |
| `dev/` | 演示数据脚本、品牌设置、RPC 进程内升级、临时验收账号等运维脚本 |
| `docker-compose.yml` | 协作者一键开发环境（Odoo 19 + PostgreSQL 18 容器，含热重载） |
| `.agent/` | 协作须知：[handoff](.agent/handoff.md)（交接要点+协作规则）、[ONBOARDING](.agent/ONBOARDING.md)（安装配置指南）、[updates](.agent/updates)（按日期的更新记录） |

> Odoo 本体源码、Python 运行时、数据库备份、`odoo.conf`、日志等本机安装产物**不入库**，见 [.gitignore](.gitignore)。

## 模块概览（tutoring_center）

数据模型：`tutoring.student`（学生档案）、`tutoring.knowledge.point`（知识点）、`tutoring.student.point`（掌握度四档）、`tutoring.session`（辅导课次）、`tutoring.topic`（教学内容标签）、`tutoring.exam` + `tutoring.exam.line`（学校考试）、`tutoring.mistake`（错题记录）；`tutoring.homework` 模型保留但已全面退出界面。

主要改造点：

- 教师后台顶栏只保留「学生」「知识点」两个菜单，全部操作从学生档案页签进入；
- 联系人（res.partner）全局简化视图，`tutoring_school` 字段与学生档案双向联动；
- 门户 `/my` 对绑定学生档案的账号直跳 `/my/learning`，门户数据按联系人隔离；
- 可通过安全组恢复被隐藏的 Odoo 原生应用菜单。

## 快速开始（协作者 · Docker 推荐）

只需装有 Docker（Windows 用 Docker Desktop / WSL2，macOS 用 Docker Desktop 或 OrbStack），**无需手动装 PostgreSQL 和 Odoo**：

```bash
git clone https://github.com/liquidsax/Odoo_Edu.git
cd Odoo_Edu
docker compose up -d        # 首次启动自动建库 + 安装 tutoring_center + 中文语言包
```

启动完成后：

- 浏览器打开 http://localhost:8069 —— 教师后台（首次账号 `admin` / `admin`，**请立即改密**）；
- 需要演示数据时执行 `./dev/seed_docker.sh`（Windows 可在 Git Bash 中运行）。

### 边开发边看效果（热重载）

`docker-compose.yml` 已带 `--dev=xml,qweb,reload`，模块源码是从仓库目录**直接挂载**进容器的：

| 改什么 | 生效方式 |
|---|---|
| 视图/数据 XML | 保存后**刷新浏览器**即生效 |
| QWeb 模板/前端 JS | 同上 |
| Python 模型/控制器 | 保存后容器**自动重启**（`--dev=reload`），稍候刷新即可 |

个别情况（如改 manifest、加字段后视图报错）需要手动升级模块：

```bash
docker compose exec odoo odoo -d edu_dev --db_host=db --db_user=odoo \
    --db_password=odoo -u tutoring_center --stop-after-init
docker compose restart odoo
```

清空环境重来：`docker compose down -v`（会删除容器内数据库与附件，不影响仓库代码）。

> 端口占用时把 compose 里的 `"8069:8069"` 改成如 `"18069:8069"`；容器内账号密码均只作用于本地开发库，勿填真实凭据。

## 本地部署（参考，维护者当前环境）

1. 安装 Odoo 19 社区版 + PostgreSQL（Windows 下注意 `db_template` 需为 C/C 排序规则的模板库，不能是 `template0`）；
2. 将 `server/addons/tutoring_center` 加入 `addons_path` 指向的自定义模块目录；
3. 升级安装模块：`odoo-bin -c odoo.conf -d <数据库名> -u tutoring_center --stop-after-init`；
4. 教师后台用 admin 登录，门户账号由教师在「学生档案 → 门户账号 → 授权门户访问」创建并直接设置初始密码（平台未开放自助注册）。

运行 `dev/seed_data.py`（在 `odoo-bin shell` 中执行）可生成演示学生、知识点、课次、考试与错题数据；演示账号密码通过环境变量 `TUTOR_DEMO_PW_A` / `TUTOR_DEMO_PW_B` 注入。

## 安全约定

- **任何真实密码、数据库凭据、`odoo.conf`、会话 cookie、数据库备份不入库**；
- 脚本中的账号密码一律走环境变量注入，默认值为占位符；
- 文档与代码中不得出现机器特定用户名路径，统一使用 `%USERPROFILE%` / `%LOCALAPPDATA%` 写法。

## 协作

- 提交前请自查：不含硬编码本机路径、不含真实学生数据与凭据；
- 修改模块 Python 代码后需重启服务并 `-u tutoring_center` 升级；纯 XML 变更可用 `dev/upgrade_via_rpc.py` 进程内升级免重启。
