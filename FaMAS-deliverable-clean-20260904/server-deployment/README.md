# 服务器部署说明

这份说明只保留交接时真正要用的内容。

## 迁移前要带走

- 代码目录
- `web/storage/`
- 需要继续生成结果时的 `code_implement/`
- 模型 API Key
- `FAMAS_SECRET_KEY`
- `FAMAS_ADMIN_PASSWORD`

如果要保留现有图谱结果，再加上默认展示数据和相关输出目录。

## 部署顺序

1. 按根目录 README 配好依赖
2. 先跑 `.\web\scripts\check-deployment-readiness.ps1`
3. 再跑 `.\web\scripts\start-single-port-local.ps1` 或 `.\web\scripts\start-public-review.ps1`

如果目标是给外部用户访问，推荐顺序是：

1. 准备公网入口。临时评审推荐使用 Cloudflare Quick Tunnel；正式服务器可使用 HTTPS 反向代理。
2. 让公网入口转发到本机服务 `http://127.0.0.1:8000`。
3. 设置稳定强密钥，至少 32 个字符。
4. 如果使用 Cloudflare Quick Tunnel，先下载 `cloudflared`：

```powershell
.\web\scripts\setup-cloudflared.ps1
```

5. 窗口 1 启动 FaMAS：

```powershell
$env:FAMAS_SECRET_KEY = "replace-with-a-long-random-secret-at-least-32-chars"
$env:FAMAS_ENABLE_DIAGNOSTICS = "0"
.\web\scripts\check-deployment-readiness.ps1 -RuntimeMode public -RunDatabaseCheck
.\web\scripts\start-public-review.ps1 `
  -SecretKey $env:FAMAS_SECRET_KEY `
  -AdminPassword "replace-with-initial-admin-password"
```

6. 窗口 2 启动 Cloudflare Quick Tunnel：

```powershell
.\web\scripts\start-cloudflared-tunnel.ps1
```

7. 复制生成的 `https://xxxxxx.trycloudflare.com`，回到窗口 1 停止 FaMAS，再带公网地址重启：

```powershell
.\web\scripts\start-public-review.ps1 `
  -SecretKey $env:FAMAS_SECRET_KEY `
  -AdminPassword "replace-with-initial-admin-password" `
  -PublicUrl "https://xxxxxx.trycloudflare.com"
```

`start-public-review.ps1` 负责以公网评审模式启动 FaMAS；`start-cloudflared-tunnel.ps1` 负责调用 `cloudflared` 生成临时公网地址。Cloudflare Quick Tunnel 地址通常会在重启 `cloudflared` 后变化。

## 关键点

- 同一套数据库迁移到新机器后，`FAMAS_SECRET_KEY` 不能随便换
- `FAMAS_ADMIN_PASSWORD` 主要只在首次初始化时用
- API Key 建议重新在页面中录入并保存，而不是写进文档
- 公网评审时注册模式会切到审核模式，新注册用户需要管理员批准后才能登录
