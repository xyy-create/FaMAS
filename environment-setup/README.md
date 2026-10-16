# 环境准备说明

这是给本地复现和服务器交接用的最小环境清单。

## 必要项

- Python 3.11 - 3.13
- Node.js 和 npm
- `web/backend` 的 Python 依赖
- `code_implement/.venv` 的流水线依赖
- MinerU pipeline 模型
- `FAMAS_SECRET_KEY`
- `FAMAS_ADMIN_PASSWORD`
- DashScope / DeepSeek API Key

## 推荐顺序

1. `.\web\scripts\setup-backend-env.ps1`
2. `.\web\scripts\setup-pipeline-env.ps1`
3. `cd web\frontend; npm install`
4. 下载 MinerU 模型
5. 运行 `.\web\scripts\start-single-port-local.ps1`

## 说明

- 真正的一键入口是根目录 README 和 `web/scripts` 下的脚本。
- 这里仅做环境前提索引，不再重复完整操作步骤。
