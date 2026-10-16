# FaMAS Web 后端

这是 FaMAS Web 应用的 FastAPI 后端，负责账号、文档、知识库、任务、图谱数据和模型设置。

## 推荐启动

优先使用根目录脚本：

```powershell
.\web\scripts\start-backend-dev.ps1
```

它会自动读取当前用户目录下的本地配置，并复用 `FAMAS_SECRET_KEY`、`FAMAS_ADMIN_PASSWORD`。

## 直接启动

如果需要手工调试，也可以在 `web/backend` 目录里运行：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
$env:FAMAS_ADMIN_PASSWORD = "<your-admin-password>"
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

## 说明

- 首次启动时，如果数据库里还没有管理员账号，需要 `FAMAS_ADMIN_PASSWORD`。
- 本地数据库默认放在 `web/storage/famas_web.db`。
- 迁移会在启动流程里自动执行，必要时也可以手工跑 Alembic。
