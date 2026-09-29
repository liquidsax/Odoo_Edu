# 协作者安装配置指南（面向 agent）

> 目标读者：接手本项目的协作者及其 agent。
> 读完本文档应能：clone 仓库 → 得到可运行的完整环境 → 自检通过 → 进入开发工作流。
> 项目背景速览见 [handoff.md](handoff.md)，面向人的总览见仓库根 [README.md](../README.md)。

---

## 路径 A：Docker 一键环境（推荐，Windows / macOS / Linux 通用）

### 前置条件

- Docker Engine 24+ 或 Docker Desktop（Windows 需启用 WSL2 后端）；
- bash（Windows 上 Git Bash 即可，用于运行 seed 脚本）；
- **不需要**本地安装 PostgreSQL 或 Odoo。

### 步骤

```bash
git clone https://github.com/liquidsax/Odoo_Edu.git
cd Odoo_Edu
git checkout main && git pull        # 动手前确保最新
docker compose up -d                 # 首次启动：拉镜像 + 建库 + 安装 tutoring_center + 中文语言包
```

首次初始化约 1~3 分钟（取决于镜像下载）。就绪判据：`docker compose logs -f odoo` 出现 `HTTP service... running` 或浏览器能打开站点。

### 初始账号与演示数据

| 事项 | 说明 |
|---|---|
| 教师后台 | http://localhost:8069/web/login ，首次 `admin` / `admin`，**登录后立即改密** |
| 网站门面 | http://localhost:8069/ ，"数学辅导 · 学习数据平台" |
| 演示数据 | `./dev/seed_docker.sh` —— 灌入知识点 + 演示学生/课次/考试/错题 + 两个门户账号 |
| 门户账号密码 | seed 脚本默认占位密码；正式测试用 `TUTOR_DEMO_PW_A=xxx TUTOR_DEMO_PW_B=yyy ./dev/seed_docker.sh` 覆盖 |

容器内的 `edu_dev` 库是**一次性开发数据**，`docker compose down -v` 即可清空重来（不影响仓库代码）。

### 开发热重载（边改边看）

`docker-compose.yml` 已带 `--dev=xml,qweb,reload`，模块源码从仓库目录直挂容器（`server/addons/tutoring_center` → `/mnt/extra-addons/tutoring_center`）：

| 改什么 | 生效方式 |
|---|---|
| 视图 / 数据 XML | 保存后**刷新浏览器** |
| QWeb 模板 / 前端 JS | 同上 |
| Python 模型 / 控制器 | 保存后容器**自动重启**（稍候刷新） |
| `__manifest__.py`、新增字段后视图报错 | 手动升级（见下） |

```bash
# 手动升级模块（个别情况需要）
docker compose exec odoo odoo -d edu_dev --db_host=db --db_user=odoo \
    --db_password=odoo -u tutoring_center --stop-after-init
docker compose restart odoo
```

### 常见问题

- **8069 端口占用**：compose 里改映射，如 `"18069:8069"`，访问 http://localhost:18069；
- **Windows 运行 seed 脚本报错**：确认在 Git Bash 中执行（不是 cmd/PowerShell）；
- **改了模型没反应**：`docker compose logs -f odoo` 看重启是否失败（多为 Python 语法错误）；
- **容器内密码规则**：compose 里的 `odoo` 数据库密码与 admin 初始密码均为开发占位值，仅限本地容器，勿填真实凭据。

---

## 路径 B：原生 Windows 安装（仅维护者当前环境参考）

维护者本机为 Windows 服务方式（Odoo 19 社区版 + PostgreSQL 18，均注册为系统服务），**不使用 Docker**。协作者一般不需要复刻此环境；如确有需要，先读 `handoff.md` 第二节与根 README 的「本地部署」与「本机已知陷阱」——尤其注意 `db_template` 必须为 C/C 排序规则模板（不能是 template0）、密码必须写在 `odoo.conf` 两条，否则会踩坑。

---

## 环境自检清单（agent 逐项验证后再开始开发）

1. `docker compose ps`：db、odoo 均为 running（或 healthy）；
2. http://localhost:8069/ 打开为"数学辅导 · 学习数据平台"门面，导航含"学习平台"；
3. admin 登录后台：顶栏菜单只有 **数学辅导（学生 / 知识点）** 与 联系人、网站；
4. 学生列表打开正常；任选学生进表单，页签（知识点掌握/学校考试/辅导课次/错题记录）渲染正常；
5. （灌过演示数据后）门户账号登录 `/my` 自动跳转 `/my/learning`，统计卡与折线图正常绘制；
6. 热重载验证：改 `views/tutoring_views.xml` 任一字符串保存 → 刷新浏览器可见变化。

---

## 开发工作流（务必遵守）

1. **开工前**：`git checkout main && git pull`；
2. **新建分支**：`feature/<主题>`（新功能）或 `fix/<主题>`（修复），如 `feature/exam-chart`、`fix/portal-403`；
3. **提交**：信息用中文，说明"改了什么、为什么"；保持仓库卫生——不提交真实密码、凭据、`odoo.conf`、备份、学生真实数据，不硬编码本机绝对路径；
4. **收尾**：push 自己的分支 → 开 Pull Request → **由管理员（liquidsax）审查后合并**；禁止直接向 `main` 推送。
