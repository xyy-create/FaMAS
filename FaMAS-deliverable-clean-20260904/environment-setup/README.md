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

## 公网下载来源

安装和首次运行会访问这些外部来源：

- PyPI：后端依赖和 `requirements.txt` 中的流水线依赖
- npm registry：`web/frontend/package.json` 中的前端依赖
- ModelScope：MinerU pipeline 模型权重
- PyTorch wheel 源：仅在使用 `.\web\scripts\setup-pipeline-env.ps1 -GpuTorch` 时需要
- GitHub release：仅在使用 `.\web\scripts\setup-cloudflared.ps1` 下载 Cloudflare Quick Tunnel 时需要
- DashScope / DeepSeek：真实模型调用和连接测试

如果目标环境不能直接访问这些地址，需要先配置代理、镜像源或离线包。本仓库不包含 wheel、npm 包、模型权重、`cloudflared` 可执行文件或真实 Key。

## 推荐顺序

1. `.\web\scripts\setup-backend-env.ps1`
2. `.\web\scripts\setup-pipeline-env.ps1`
3. `cd web\frontend; npm install`
4. 下载 MinerU 模型
5. 如需临时公网访问，运行 `.\web\scripts\setup-cloudflared.ps1`
6. 运行 `.\web\scripts\start-single-port-local.ps1`

## 说明

- 真正的一键入口是根目录 README 和 `web/scripts` 下的脚本。
- 这里仅做环境前提索引，不再重复完整操作步骤。
- 临时公网访问推荐使用 Cloudflare Quick Tunnel：先运行 `start-public-review.ps1` 启动本机服务，再运行 `start-cloudflared-tunnel.ps1` 生成临时公网地址。
