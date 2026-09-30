# Odoo 服务启停与体检（skill：`odoo-service-control`）

> **适用范围**：维护者本机的**原生 Windows 服务栈**——`odoo-server-19.0`（HTTP 8069）+ `postgresql-x64-18`（5432）。
> 协作者若走 Docker 路径（[ONBOARDING.md](ONBOARDING.md) 路径 B），启停就是 `docker compose up -d` / `down`，本文不适用。
> 本机环境细节见 [README.md](README.md)；模块升级、备份等其他运维见 README 第八节。

---

## 一、工具与调用

启停与体检统一走 Qoder skill `odoo-service-control` 的脚本 `svcctl.ps1`。

**不要手搓 `Start-Service` / `Stop-Service` 一行流**——脚本已经处理了提权结果回传、两个服务的启停顺序、以及"等到状态真正稳定"这三件容易出错的事。

| 位置 | 说明 |
|---|---|
| `%USERPROFILE%\.qoder-cn\skills\odoo-service-control\scripts\svcctl.ps1` | skill 安装位置，**权威版本** |
| `.agent/scripts/svcctl.ps1` | 仓库内副本（换机或 skill 丢失时可用；如有出入以 skill 内版本为准） |

```bash
powershell -NoProfile -ExecutionPolicy Bypass -File \
  "%USERPROFILE%\.qoder-cn\skills\odoo-service-control\scripts\svcctl.ps1" <action> <target> [lines]
```

## 二、action 与 target

| action | 需要管理员 | 作用 |
|---|---|---|
| `start` | 是（弹 UAC） | 启动并等到 `Running` |
| `stop` | 是（弹 UAC） | `-Force` 停止并等到 `Stopped` |
| `restart` | 是（弹 UAC） | 重启并等到恢复 |
| `status` | 否 | 服务状态 / 启动类型 + 5432、8069 的归属进程 |
| `logs` | 否 | `odoo.log`（及最新 PostgreSQL 日志）尾部 |
| `check` | 否 | 六层体检，见第四节 |

| target | 解析为 |
|---|---|
| `odoo` | `odoo-server-19.0` 单个 |
| `pg` | `postgresql-x64-18` 单个 |
| `all` | 两者；**启动**按 PG → Odoo，**停止**按 Odoo → PG |

`[lines]` 只对 `logs` 生效（默认 30，上限 500）。

## 三、UAC：变更动作前必须先告知用户

`start` / `stop` / `restart` 会自提权（`Start-Process -Verb RunAs`），因为 agent 的 shell 本身不是管理员：

- **执行前先告诉用户"马上会弹 UAC 窗口，请点『是』"**；一次变更动作弹一次；
- 调用方（agent）需把命令超时设到 **≥ 300000 ms**——脚本会 `-Wait` 阻塞在用户做决定上；
- 输出出现 `[FAIL] UAC was declined` 表示用户取消了，**不要静默重试**，如实上报；
- 若当前 shell 已持有管理员令牌，则不弹窗（脚本自行判断）。

## 四、推荐流程：变更 → 必须复核

1. 先 `status all` 看现状（免提权）；
2. 执行变更动作（先告知 UAC）；
3. **必须再跑 `check` 复核**——服务 `Running` 不等于可用，Odoo 完全可能起来了却连不上数据库。

`check` 校验六层：

1. 服务状态 + 端口归属进程；
2. `odoo.conf` 的 `db_user` / `db_password` / `db_template` 三个键（配置路径从 nssm 服务注册表自动发现）；
3. 用该凭据真实登录一次 `psql`；
4. 每个库的 `datcollate` vs `datctype`（Windows 不容忍两者不一致）；
5. HTTP `http://127.0.0.1:8069/web/database/list`；
6. `odoo.log` 里的错误行——**限定在本次进程启动时间窗内**，历史噪声不会误报为当前故障。

## 五、失败判读

| 输出症状 | 原因 / 下一步 |
|---|---|
| `db_password set: NO` / `fe_sendauth: no password supplied` | Odoo 拿不到凭据：服务以 `LocalSystem` 运行，读不到用户目录的 `pgpass.conf` → 在 `odoo.conf` 写 `db_password` 后 `restart odoo` |
| 第 4 节某库 collate ≠ ctype（如 C vs English_United States.936） | 建库时 `db_template` 踩了 `template0` → 见 README 陷阱 1：必须保持 `db_template = odoo_template_c`，已存在的库只能删库重建 |
| 服务与端口都正常，但第 5 节 HTTP 失败 | Odoo 起来了、数据层坏 → 看第 6 节与 `logs odoo 80` |
| 8069 `not listening` 而服务显示 `Running` | Odoo 正在启动或崩溃重启中 → `logs odoo 60` |
| `service not installed` | 服务被卸载或改名 → `Get-Service` 确认 |

## 六、红线

- **取最小动作**：改完 `odoo.conf` 用 `restart odoo`，不要顺手重启 PostgreSQL；确要动 PG，先说清会连带停掉什么。
- `stop all` 会让整个平台下线——执行前确认用户不在使用中。
- 脚本只管服务与读日志：**不建库、不装模块、不改 `odoo.conf`**，这些需要另行明确授权。
- 升级 `tutoring_center` 按变更类型选方式（Python 变更必须重启服务；纯 XML/数据变更可用 `dev/upgrade_via_rpc.py` 免重启），见 README 第八节。
