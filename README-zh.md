# FaMAS

FaMAS（figure-aware multi-agent system，图像感知多智能体系统）从教材 PDF 构建知识图谱，并把教材原生图片作为可追溯证据保留下来。

![FaMAS 流程](assets/famas-pipeline.jpg)

## 系统由两部分组成

- **FaMAS 流水线**（`code_implement/`）：把教材 PDF 解析、切分、抽取、校验、合并成知识图谱。
- **FaMAS Web 应用**（`web/`）：把流水线包装成可登录的多用户界面，负责文档管理、图谱浏览与人工修正、基于图谱的问答。

流水线可以单独在 Linux / macOS 上运行；Web 应用目前的一键脚本是 Windows PowerShell 版，内部调用的是同一套流水线。

## 先说明系统范围

- **Windows PowerShell**：完整支持 Web 启动、依赖安装和一键本地运行。
- **Linux / macOS**：适合跑 `code_implement/` 流水线和静态可视化；Web 一键脚本目前是 PowerShell 版。

## 目录职责

- `web/`：前后端 Web 应用
- `code_implement/`：FaMAS 流水线
- `textbook/`：默认教材输入
- `visualization/chemistry/`：化学图谱静态查看器

历史过程文档和本地笔记不纳入最终转交包。

## 一、FaMAS 流水线

### 1. 创建 Python 环境

```bash
python3.11 -m venv code_implement/.venv
source code_implement/.venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Windows 下这一步可以直接用 `.\web\scripts\setup-pipeline-env.ps1` 代替（见 Web 应用部分）。

### 2. 配置模型 Key

```bash
export DASHSCOPE_API_KEY="<your-dashscope-key>"
export DEEPSEEK_API_KEY="<your-deepseek-key>"
```

### 3. 下载 MinerU 模型

请在**仓库根目录**执行这一步，且先 `source code_implement/.venv/bin/activate`。

```bash
export MODELSCOPE_CACHE="$PWD/code_implement/.models/modelscope"
mineru-models-download --source modelscope --model_type pipeline
export MINERU_MODEL_SOURCE="local"
```

### 4. 运行流水线

```bash
python -m mas.pipelines.full_pipeline.main \
  --pdf "textbook/普通高中教科书·化学必修 第一册.pdf" \
  --subject 化学 \
  --grade high_school \
  --publisher sujiao \
  --run-id chemistry_full_famas
```

加 `--mock` 可以跳过真实模型调用，只跑通流程。

### 5. 运行静态可视化

```bash
cd visualization/chemistry
python -m http.server 8000
```

然后打开 `http://127.0.0.1:8000/`。

## 二、FaMAS Web 应用

### 提供什么功能

| 页面 | 功能 |
| --- | --- |
| 文档 | 上传 PDF（大文件走分片上传）、查看处理状态和各阶段日志、编辑文档元信息（学科 / 年级 / 出版社 / 教材版本）、触发 PDF 解析与图谱构建、管理 schema 版本 |
| 知识图谱 | 浏览已构建的图谱（节点 / 关系 / 三元组）、查看节点对应的教材原图、按知识库和文档筛选 |
| 书脉问答 | 针对当前知识库提问，流式返回答案，并给出关键依据：相关节点、相关三元组和教材原始出处 |
| 用户 | 仅管理员可见。管理账号（启用 / 停用、重置密码、审批注册），查看每个用户的 API Key 状态以及各自的人工修正层、人工标注层 |
| 设置 | 账号信息和改密、运行环境与存储 / 任务状态、访问模式（注册方式）、知识库管理、模型设置（DashScope / DeepSeek 的 Key 与模型名，由后端加密保存）、临时公网访问入口 |

除页面功能外，还有一层「人工修正 + 人工标注」：

- 可以覆盖节点的标题和说明、隐藏节点、修改或新增关系和三元组，也可以按模板给知识点打标注。
- 修正按用户隔离保存，原始流水线产物不被改写；读取图谱数据时按当前用户合并后再返回。

### 组成

- `web/frontend/`：Vue 3 + Vite。开发态通过 Vite 代理把 `/api` 转发到后端；生产态由后端直接托管构建产物，实现单端口访问。
- `web/backend/`：FastAPI + SQLAlchemy + Alembic。负责登录鉴权、知识库 / 文档 / 任务管理、图谱读写、模型调用和 API Key 加密存储。
- `web/storage/`：运行期数据（SQLite 数据库、图谱产物、上传文件），属于要保留的数据。
- `web/scripts/`：PowerShell 启动和维护脚本。

### 启动（Windows PowerShell）

#### 1. 环境准备

三个环境互相独立，各装一次即可：

| 命令 | 作用 |
| --- | --- |
| `.\web\scripts\setup-backend-env.ps1` | 创建 `web/backend/.venv` 并安装后端依赖 |
| `.\web\scripts\setup-pipeline-env.ps1` | 创建 `code_implement/.venv` 并安装流水线依赖 |
| `cd web\frontend; npm install` | 安装前端依赖 |

如需 GPU 版 PyTorch：

```powershell
.\web\scripts\setup-pipeline-env.ps1 -GpuTorch
```

#### 2. MinerU 模型下载

请在**仓库根目录**执行这一步，并先激活流水线环境，否则 `mineru-models-download` 可能找不到。

```powershell
.\code_implement\.venv\Scripts\Activate.ps1
$env:MODELSCOPE_CACHE = "$PWD\code_implement\.models\modelscope"
mineru-models-download --source modelscope --model_type pipeline
$env:MINERU_MODEL_SOURCE = "local"
```

如果不想先激活，也可以直接用完整路径：

```powershell
$env:MODELSCOPE_CACHE = "$PWD\code_implement\.models\modelscope"
.\code_implement\.venv\Scripts\mineru-models-download.exe --source modelscope --model_type pipeline
```

#### 3. 一键启动（推荐）

```powershell
.\web\scripts\start-single-port-local.ps1
```

这个脚本会：

- 自动检查后端、流水线、前端依赖
- 缺环境时提示具体安装命令
- 自动执行 `npm run build`
- 构建失败直接退出
- 首次运行交互输入并保存 `FAMAS_SECRET_KEY` 和 `FAMAS_ADMIN_PASSWORD`
- 下次自动读取当前用户目录下的 `~/.famas/famas/local-config.json`

启动后的访问地址：

```text
访问入口：  http://127.0.0.1:8000
健康检查：  http://127.0.0.1:8000/api/health
就绪检查：  http://127.0.0.1:8000/api/health/ready
```

注意单端口模式托管的是 `web/frontend/dist` 里的构建产物，**改了 Vue / CSS / 化学查看器源码不会热更新**，需要改完重新跑这个脚本；后端 Python 代码则默认会热重载（`-NoBackendReload` 可关闭）。

#### 4. 本地开发

前后端分开跑，两边都能热更新：

```powershell
.\web\scripts\start-backend-dev.ps1
.\web\scripts\start-frontend-dev.ps1
```

前端开发服务器通过 Vite 代理把 `/api` 转发到 `http://127.0.0.1:8000`。

#### 5. 临时公网评审

```powershell
.\web\scripts\start-public-review.ps1
```

脚本会通过 Cloudflare Quick Tunnel 把本地服务暴露到公网。Quick Tunnel 是**临时地址**：每次重启通常会生成新的 `trycloudflare.com` 地址，关闭后旧地址失效，不要把这类地址写进文档或仓库。

### 常用维护脚本

| 脚本 | 作用 |
| --- | --- |
| `check-deployment-readiness.ps1` | 部署前自检，常用 `-RunDatabaseCheck -RequireFrontendBuild` |
| `check-running-server.ps1` | 检查本地服务是否已经起来 |
| `migrate-backend-db.ps1` | 手工执行数据库迁移，`-CheckOnly` 只校验不执行 |
| `backup-local-data.ps1` | 备份本地数据到指定目录，`-DryRun` 可先预览 |

## 密钥和页面配置

- `FAMAS_SECRET_KEY` 负责登录签名和后端保存的 API Key 加密。
- `FAMAS_ADMIN_PASSWORD` 只在首次创建管理员时需要。
- DashScope / DeepSeek 的 API Key 在 Web 界面「设置 → 模型设置」里录入，由后端加密保存。
- 如果以后更换 `FAMAS_SECRET_KEY`，历史 API Key 需要重新保存。

完整的可配置项见 `web/backend/.env.example`。

## 默认保留的数据

以下内容是默认要保留的，不应当当成一次性测试产物删掉：

- `默认知识库/`
- `web/storage/`
- `code_implement/data/examples/chemistry/`
- `visualization/chemistry/data/`
- `visualization/chemistry/assets/images/`

其它运行缓存、中间产物、构建输出、测试残留和本地笔记都不应放进最终转交包。

## 回退

分支是 `main`。需要回退时先看提交历史，再按提交号切换或另开分支：

```powershell
git log --oneline
git switch -c backup <commit>
```
