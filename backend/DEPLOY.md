# ChiShenMe Backend — 部署指南

> 版本: 2026-05 | 仓库: github.com/122754048/chishenme-rn (master)
> 对应文件路径均为仓库相对路径。

---

## 目录

1. [目录结构说明](#1-目录结构说明)
2. [部署平台对比](#2-部署平台对比)
3. [推荐方案：Railway（详细步骤）](#3-推荐方案railway详细步骤)
4. [备选方案：fly.io](#4-备选方案flyio)
5. [备选方案：Render](#5-备选方案render)
6. [本地 docker-compose 开发 / 预生产测试](#6-本地-docker-compose-开发--预生产测试)
7. [数据库切换：SQLite → PostgreSQL](#7-数据库切换sqlite--postgresql)
8. [Alembic 迁移](#8-alembic-迁移)
9. [生产环境变量清单](#9-生产环境变量清单)
10. [安全加固建议](#10-安全加固建议)
11. [健康检查端点](#11-健康检查端点)

---

## 1. 目录结构说明

```
chishenme-rn/
├── backend/                  ← FastAPI 应用根目录（Docker build context）
│   ├── Dockerfile            ← 多阶段构建，非 root，< 300MB
│   ├── alembic.ini           ← Alembic 迁移配置
│   ├── alembic/
│   │   ├── env.py            ← 自动读取 DATABASE_URL / 回退 SQLite
│   │   ├── script.py.mako
│   │   └── versions/
│   │       └── 0001_initial_schema.py
│   ├── requirements.txt      ← 含 psycopg2-binary==2.9.9
│   └── app/
│       ├── main.py           ← FastAPI 路由（无需修改）
│       ├── db.py             ← 统一 DB 入口，自动切换 SQLite / PG
│       ├── config.py         ← 环境变量配置
│       ├── schemas.py
│       ├── security.py
│       └── services/
├── docker-compose.yml        ← 仓库根目录，含 PG + API 服务
└── .dockerignore             ← 仓库根目录
```

---

## 2. 部署平台对比

| 维度 | Railway | fly.io | Render |
|------|---------|--------|--------|
| **上手难度** | ⭐ 最简单，GUI + CLI | 中等，CLI 为主 | 简单，Git 触发 |
| **免费额度** | $5/月免费额度 | 共享 CPU 免费机器（有限） | 免费实例（冷启动慢 ~30s） |
| **PostgreSQL** | 内置一键创建 | 内置托管，需 fly postgres | 免费 90 天，之后收费 |
| **冷启动** | 无 | 无 | 免费层有冷启动 |
| **Docker 支持** | 原生，自动识别 Dockerfile | 原生，flyctl deploy | 原生 |
| **推荐场景** | 原型 → 生产，快速迭代 | 需要多区域/低延迟 | 静态 + API 混合项目 |

---

## 3. 推荐方案：Railway（详细步骤）

### 前置条件

```bash
npm install -g @railway/cli
railway login
```

### 步骤 1：创建项目并添加 PostgreSQL

```bash
cd backend/
railway init
railway add -d postgresql   # 自动注入 DATABASE_URL
```

### 步骤 2：设置环境变量

```bash
railway variables set JWT_SECRET=$(openssl rand -hex 32)
railway variables set APP_ENV=production
railway variables set FREE_DAILY_QUOTA=3

# 按需设置外部 API
railway variables set OPENAI_API_KEY=sk-...
railway variables set GOOGLE_PLACES_API_KEY=AIza...
railway variables set ALIPAY_APP_ID=...
railway variables set ALIPAY_PUBLIC_KEY=...
railway variables set REVENUECAT_WEBHOOK_SECRET=...
railway variables set REVENUECAT_PRO_PRODUCT_ID=teller.pro.monthly
railway variables set REVENUECAT_FAMILY_PRODUCT_ID=teller.family.monthly
```

### 步骤 3：部署

```bash
# 在 backend/ 目录下执行
railway up
```

Railway 自动检测 `backend/Dockerfile`，注入 `DATABASE_URL`，启动后调用 `/health` 验证。

### 步骤 4：运行数据库迁移

```bash
# 在 Railway CLI 中执行 alembic
railway run alembic upgrade head
```

### 步骤 5：获取公网 URL

```bash
railway domain
# 例: https://chishenme-production.up.railway.app
```

### 步骤 6：验证健康端点

```bash
curl https://chishenme-production.up.railway.app/health
# → {"status":"ok"}
```

### 步骤 7：更新前端

```bash
# Expo 环境变量
EXPO_PUBLIC_API_BASE_URL=https://chishenme-production.up.railway.app
```

---

## 4. 备选方案：fly.io

```bash
brew install flyctl
flyctl auth login
cd backend/

flyctl launch --name chishenme-api --region nrt  # nrt=东京

# 创建 PostgreSQL 集群
flyctl postgres create --name chishenme-pg --region nrt
flyctl postgres attach chishenme-pg --app chishenme-api
# 自动注入 DATABASE_URL

flyctl secrets set \
  JWT_SECRET=$(openssl rand -hex 32) \
  APP_ENV=production \
  OPENAI_API_KEY=sk-... \
  GOOGLE_PLACES_API_KEY=AIza...

flyctl deploy
```

**fly.toml 健康检查配置：**

```toml
[[services.http_checks]]
  interval = "30s"
  path = "/health"
  timeout = "5s"
```

---

## 5. 备选方案：Render

1. New → Web Service → Connect GitHub → 选 `122754048/chishenme-rn`
2. 配置：
   - **Root Directory**: `backend`
   - **Runtime**: Docker
   - **Dockerfile Path**: `./Dockerfile`
3. New → PostgreSQL → 同一地区 → 复制 `DATABASE_URL`
4. Environment 添加所有必需变量（见第 9 节）
5. Create Web Service → 等待构建

> ⚠️ Render 免费层 15 分钟不活跃后休眠，生产环境建议 Starter 计划（$7/月）。

---

## 6. 本地 docker-compose 开发 / 预生产测试

```bash
# 在仓库根目录
cat > .env << 'EOF'
POSTGRES_PASSWORD=localdevpwd
JWT_SECRET=local-dev-secret-change-in-prod
APP_ENV=development
FREE_DAILY_QUOTA=3
EOF

docker-compose up --build

# 验证
curl http://localhost:8000/health
# → {"status":"ok"}

curl -X POST http://localhost:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{"user_id":"test@example.com","password":"testpass"}'
```

---

## 7. 数据库切换：SQLite → PostgreSQL

`backend/app/db.py` 在启动时自动检测：

| 条件 | 使用后端 |
|------|---------|
| `DATABASE_URL` 以 `postgres://` 或 `postgresql://` 开头 | PostgreSQL |
| 其他（包括未设置） | SQLite（路径由 `DB_PATH` 控制） |

**无需修改任何业务代码**，`tx()` context manager 接口保持不变。

切换步骤：

```bash
# 1. 设置环境变量（本地测试）
export DATABASE_URL=postgresql://chishenme:password@localhost:5432/chishenme

# 2. 运行迁移
cd backend/
alembic upgrade head

# 3. 启动服务
uvicorn app.main:app --reload
```

---

## 8. Alembic 迁移

```bash
cd backend/

# 应用所有迁移
alembic upgrade head

# 查看迁移状态
alembic current

# 生成新迁移（修改 schema 后）
alembic revision --autogenerate -m "add new table"

# 回滚一步
alembic downgrade -1
```

初始迁移文件：`backend/alembic/versions/0001_initial_schema.py`

---

## 9. 生产环境变量清单

### ✅ 必需

| 变量名 | 说明 | 示例 |
|--------|------|------|
| `DATABASE_URL` | PostgreSQL 连接串 | `postgresql://user:pwd@host:5432/chishenme` |
| `JWT_SECRET` | JWT 签名密钥，随机生成 | `openssl rand -hex 32` |
| `APP_ENV` | 运行环境 | `production` |

### ⚙️ 强烈建议

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `FREE_DAILY_QUOTA` | `3` | 免费用户每日 AI 调用次数 |
| `JWT_EXP_MINUTES` | `43200`（30天） | Token 有效期 |
| `OPENAI_API_KEY` | 空 | `/discovery/menu-scan` 端点必需 |
| `GOOGLE_PLACES_API_KEY` | 空 | `/discovery/nearby-restaurants` 端点必需 |

### 💳 支付集成

| 变量名 | 说明 |
|--------|------|
| `ALIPAY_APP_ID` | 支付宝应用 ID |
| `ALIPAY_PUBLIC_KEY` | 支付宝公钥（`/billing/alipay/notify` 验签） |
| `REVENUECAT_WEBHOOK_SECRET` | RevenueCat Webhook 密钥（`/billing/revenuecat/webhook`） |
| `REVENUECAT_ENTITLEMENT_ID` | 默认 `premium` |
| `REVENUECAT_PRO_PRODUCT_ID` | 如 `teller.pro.monthly` |
| `REVENUECAT_FAMILY_PRODUCT_ID` | 如 `teller.family.monthly` |

### 🐘 PostgreSQL（docker-compose 专用）

| 变量名 | 说明 |
|--------|------|
| `POSTGRES_PASSWORD` | **必需**，强密码 |
| `POSTGRES_USER` | 默认 `chishenme` |
| `POSTGRES_DB` | 默认 `chishenme` |

---

## 10. 安全加固建议

### JWT_SECRET 管理

```bash
# ✅ 正确：每个环境独立随机生成
openssl rand -hex 32

# ❌ 错误：使用默认值 "replace-in-prod"
# config.py 的 assert_runtime_safe() 在 APP_ENV=production 时阻止启动
```

### HTTPS

Railway / fly.io / Render 均自动提供 TLS 终止，无需在 FastAPI 层处理。

### 数据库密码生成

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

### .env 文件

永远不要提交 `.env` 到 Git。确认 `.gitignore` 包含 `.env`。

---

## 11. 健康检查端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `GET /health` | GET | 返回 `{"status":"ok"}`，Docker HEALTHCHECK 使用此端点 |
| `GET /plans` | GET | 返回套餐列表（无需认证） |

Docker HEALTHCHECK 配置（已在 `backend/Dockerfile` 中）：

```dockerfile
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1
```

---

*生成时间: 2026-05-06 | 文档版本: v2*
