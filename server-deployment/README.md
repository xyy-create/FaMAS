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

## 关键点

- 同一套数据库迁移到新机器后，`FAMAS_SECRET_KEY` 不能随便换
- `FAMAS_ADMIN_PASSWORD` 主要只在首次初始化时用
- API Key 建议重新在页面中录入并保存，而不是写进文档
