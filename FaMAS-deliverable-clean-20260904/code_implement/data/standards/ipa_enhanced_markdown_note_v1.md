# IPA Enhanced Markdown Note v1 Standard

## 说明目的

本文档是 `code_implement/data` 下的数据格式标准说明，定义当前 IPA（Image Processing Agent）写入增强 Markdown 的标准化 note 格式。该 note 是 IPA 的机器可读辅助信息块，不属于可选方案、不是草案，也不是教材原文。

后续 KG agent 读取增强 Markdown 时，必须把 `Image Processing Agent` note 视为 agent metadata / evidence，而不是普通课文。KG 抽取应优先依据 `KG 价值` 与 `处理结果` 的可靠性判断是否进入候选事实抽取，不应把某一次 ITA taxonomy 的具体类别名称写死为长期规则。

## 标准块位置

IPA note 紧跟在对应的原始图片链接之后。原始图片链接必须保留，IPA note 不替代图片，也不应新增 Markdown 图片语法。

标准位置如下：

```md
![](images/xxx.jpg)

> [!NOTE] Image Processing Agent
> Image ID：<image_id>
> 图片类型：<image_type_id>
> KG 价值：<high|medium|low|uncertain>
> 处理状态：<accepted|medium_described|skipped_low|fallback_uncertain|degraded|...>
> 处理结果：<单行结果>
```

当第二轮文本化结果是多行内容时，标准格式如下：

````md
![](images/xxx.jpg)

> [!NOTE] Image Processing Agent
> Image ID：<image_id>
> 图片类型：<image_type_id>
> KG 价值：<high|medium|low|uncertain>
> 处理状态：<accepted|medium_described|skipped_low|fallback_uncertain|degraded|...>
> 处理结果：
> ```
> <round2 文本化内容>
> ```
````

## 字段含义

`[!NOTE] Image Processing Agent` 是 IPA note 的起始标记。后续 agent 可以用它识别该块的边界和来源。

`Image ID` 是本次 IPA 运行中对应 Markdown 图片引用的稳定局部编号。历史 v1 note 可能没有该字段；解析器必须保持兼容。

`图片类型` 是 IPA round1 基于当轮 ITA taxonomy 给出的分类结果。它用于 provenance、审计和人工排查，不作为后续 KG 抽取的固定硬规则。ITA taxonomy 可能随教材、样本、模型或参数重跑而变化，因此后续 agent 不应依赖具体 `image_type_id` 名称写死抽取策略。

`KG 价值` 是 IPA 对该图片是否可能支持 KG 构建的价值判断，是后续 KG agent 的主要决策字段。当前合法值为：

- `high`：图片具有较高 KG 价值，若 `处理结果` 给出可靠文本化内容，可进入候选 KG evidence。
- `medium`：图片具有一定 KG 价值，通常作为上下文或辅助 evidence；是否抽取事实需更谨慎。
- `low`：图片对 KG 构建价值较低，默认不抽取 KG fact。
- `uncertain`：IPA 无法稳定判断价值，默认不抽取 KG fact。

`处理结果` 是 IPA 对该图片的最终处理状态，可能包括：

- 明确的文本化内容或短描述。
- `该图片暂不提取文本化内容。`
- `该图片保留原图链接和价值标记，未生成文本化内容。`
- `第二轮处理失败：...`
- 其他审计失败或模型输出失败说明。

`处理状态` 是对 IPA 分层流转结果的机器可读枚举。历史 v1 note 可能没有该字段；没有该字段时，KG 解析器按 `KG 价值` 和 `处理结果` 做兼容判断。当前常见值包括：

- `accepted`：高价值图片完成完整 IPA Round2，并通过 verifier/critic。
- `medium_described`：中价值图片完成轻量描述，保留 FigureRef，是否进入 KG 需由 KG extractor 谨慎判断。
- `skipped_low`：低价值图片不做复杂文本化，只保留原图、价值判断和 trace audit。
- `fallback_uncertain`：不确定图片生成轻量 fallback 描述或进入复核队列，不作为教材事实证据。
- `degraded`：高/中价值图片经过多轮 generator/verifier 仍未收敛，增强 Markdown 只保留最后一轮可用候选描述和降级说明；verifier/critic issues 只写入 audit 文件。
- `failed`、`rejected`、`classification_missing`、`missing_image_file`：处理失败或源图缺失，不作为 KG fact evidence。

完整追溯记录写入 IPA run 目录下的 `audit/image_trace_audit.json` 与 `audit/image_trace_audit.jsonl`。每条记录至少包含 `image_id`、`figure_id`、`image_path`、`source_pdf`、`source_page`、`source_section_id`、`source_markdown_path`、`kg_value`、`processing_status`、跳过/降级/fallback 原因、最后候选描述是否存在，以及 `final_ipa_note_written`。未进入 section Markdown 的 MinerU/PDF 图片会以 `processing_status=not_in_section_markdown` 进入 trace audit，但不会写入 enhanced Markdown note。

## KG 抽取兼容规则

后续 KG agent 应采用以下兼容规则解释当前 v1 IPA note。

1. 当 `KG 价值` 为 `low` 或 `uncertain` 时，默认不抽取 KG fact，只保留 provenance / evidence 记录。
2. 当 `处理结果` 包含 `暂不提取文本化内容` 时，不抽取 KG fact。
3. 当 `处理结果` 包含 `第二轮处理失败`、`未通过审计` 或其他失败说明时，不抽取 KG fact。
4. 当 `处理结果` 为 `保留原图链接和价值标记，未生成文本化内容。` 时，只作 evidence / provenance，不直接抽取事实。
5. 当 `KG 价值` 为 `high` 或 `medium`，且 `处理结果` 是明确、可读、非失败的文本化内容时，可以作为候选 KG evidence，但 KG extractor 仍需自行进行实体识别、关系判断、事实校验和来源标注。
6. `图片类型` 可以作为辅助上下文或审计字段，但不应单独决定是否抽取 KG fact。
7. 当 `处理状态` 为 `degraded`、`skipped_low`、`fallback_uncertain`、`uncertain_no_fallback`、`classification_missing`、`missing_image_file`、`failed` 或 `rejected` 时，不抽取 KG fact。特别是 verifier/critic 的反馈、issues、revision hint 不能写入 enhanced Markdown，也不能作为教材事实进入 KG。

## 与教材正文的边界

IPA note 不属于教材原文。后续 agent 生成 KG 时，应区分以下来源：

- 教材正文：原始 Markdown 中的标题、段落、题目、表格、公式等内容。
- 原始图片：保留的 `![](images/xxx.jpg)` 链接。
- IPA note：IPA 生成的图片分类、KG 价值判断、文本化结果或失败说明。

如果 KG fact 来自 IPA note 的文本化内容，来源应标记为 IPA-generated evidence，并尽量保留对应图片链接、所在小节、`图片类型`、`KG 价值` 和 `处理结果` 摘要，便于后续审计。

## 当前 v1 与未来 v2 的边界

当前增强 Markdown 中的 IPA note 使用 v1 兼容格式，并允许新增 `Image ID` 和 `处理状态` 两个可选字段。历史 note 缺少这些字段时仍应可解析；新 run 应写入这两个字段并同步生成 trace audit。

如果未来需要增加更显式的字段，例如 `schema`、`audit_status`、`round2_status`、`extraction_policy`、`extraction_confidence` 或 `model_confidence`，应作为 IPA note v2 单独规划，并保持对 v1 的兼容解析。
