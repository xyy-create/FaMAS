# FaMAS 化学知识图谱可视化

本目录是前端 Web 应用内嵌使用的静态知识图谱查看器副本，内容来自 `visualization/chemistry/`。当前 Vue 前端通过 iframe 加载这里的 `index.html`，用于保留原静态版完整交互逻辑。

## 运行方式

在正常开发时，不需要单独启动本目录。启动前端后，Vue 页面会从下面路径加载查看器：

```text
/chemistry/index.html
```

如果需要单独调试这个静态查看器，可以在本目录启动 HTTP 服务：

```bash
python -m http.server 8000
```

然后打开：

```text
http://127.0.0.1:8000/
```

## 功能

- 三元组搜索与关系筛选。
- 节点、边、三元组详情查看。
- 画布平移、缩放、旋转和节点拖动。
- FigureRef 教材图片预览。
- 可调整尺寸的详情面板和全局缩略图。
- 中英文数据与界面切换。

## 数据规模

| 项目 | 数量 |
| --- | ---: |
| 节点 | 85 |
| 边 | 82 |
| 三元组 | 82 |
| FigureRef 图片 | 60 |

## 目录结构

```text
public/chemistry/
├─ assets/
│  ├─ images/
│  └─ preview.png
├─ data/
│  ├─ en/
│  └─ zh/
├─ app.js
├─ index.html
├─ minimap-helpers.js
└─ styles.css
```

## 注意

这是只读查看器，不负责上传、编辑、保存或导出图谱数据。后续如果把图谱逻辑完全迁移到 Vue 组件中，需要再把 `app.js` 中的全局脚本逻辑拆分为可维护的模块。
