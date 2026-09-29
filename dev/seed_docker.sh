#!/usr/bin/env bash
# 在 Docker 开发容器内灌入演示数据（知识点 + 学生/课次/考试/错题 + 门户账号）。
# 用法：先 `docker compose up -d` 且首次初始化完成（浏览器能打开 http://localhost:8069），
# 然后执行本脚本。演示账号密码可用环境变量覆盖：
#   TUTOR_DEMO_PW_A=xxx TUTOR_DEMO_PW_B=yyy ./dev/seed_docker.sh
set -e
cd "$(dirname "$0")/.."

run_shell() {
    docker compose exec -T odoo odoo shell -d edu_dev \
        --db_host=db --db_user=odoo --db_password=odoo < "$1"
}

echo "== 灌入知识点 =="
run_shell dev/seed_knowledge.py
echo "== 灌入演示学生/课次/考试/错题 =="
run_shell dev/seed_data.py
echo "== 完成：门户账号见 seed_data.py 输出 =="
