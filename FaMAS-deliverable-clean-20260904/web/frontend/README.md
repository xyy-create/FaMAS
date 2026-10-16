# FaMAS Web 前端

这是 FaMAS Web 应用的 Vue + Vite 前端。

## 推荐启动

优先使用：

```powershell
.\web\scripts\start-frontend-dev.ps1
```

如果要看最终构建结果，使用单端口脚本：

```powershell
.\web\scripts\start-single-port-local.ps1
```

## 直接启动和构建

```powershell
cd web\frontend
npm install
npm run dev
```

构建命令：

```powershell
npm run build
```

`dist/` 是构建产物，不应纳入最终转交包。

## 页面约定

- `API` 页面用于录入 DashScope / DeepSeek Key
- Key 由后端加密保存，不直接放在前端静态文件里
- `Knowledge Graph` 页面继续使用本地图谱查看器
