# KG Schema Label/Property v2 Standard

## 标准来源

- 来源 run：`schema_real_20260812_003406_chemistry_required1_after_stagefix_20260812_real`
- schema_version：`kg.schema.label_property.v2`
- schema_contract：`label_property_v2`
- model：`qwen3.5-flash`
- mock：`False`

## 机器可读文件

同目录下的 `kg_schema_label_property_v2.json` 是正式 KG schema contract。后续 Node Extraction 和 Edge Extraction 必须以该 JSON 为准。

## Node Labels

- `KnowledgePoint`
- `Problem`
- `ChapterSection`
- `Element`
- `ChemicalSubstance`
- `Ion`
- `ChemicalCategory`
- `SolubilityRule`

## Edge Labels

- `contains`
- `tests`
- `requires`
- `prerequisite_for`
- `extends`
- `uses_method`
- `precipitates_with`
- `composed_of`
- `classified_as`
- `belongs_to_group`

## Shared Property Types

- `EvidenceRef`
- `FigureRef`
- `RuleStatement`
- `MethodStep`
- `FormulaStatement`
- `QuantityRelationship`
- `ToolRef`
- `ExampleRef`
- `ChemicalFormula`
- `BilingualTerm`

## Evidence And Confidence Policy

- evidence policy 来自 JSON 的 `evidence_policy`。
- confidence policy 来自 JSON 的 `confidence_policy`。
- IPA note 仍按 `ipa_enhanced_markdown_note_v1.md` 处理：IPA note 是 metadata/evidence，不是教材正文。

## Extraction Boundaries

- IPA note 是图片经视觉模型文本化的结果，不是教材正文本体；其作用是判断该图属于哪个 node/edge 后作为 FigureRef 挂入其 figures，与 EvidenceRef 无关。
- 图像一律通过 FigureRef 进入 KG，永不进入 EvidenceRef；EvidenceRef 只承载文字上下文证据。
- Do not extract KG facts from low/uncertain or failed IPA notes.
- Property-like candidates are node/edge properties unless a strong promotion_reason is provided.
- The human base schema is an educational prior, not a closed label set; SA may add evidence-grounded subject-level labels and predicates while avoiding textbook-local label explosion.

## 使用规则

- Node Extraction 只能创建 `node_labels` 中定义的节点标签。
- Edge Extraction 只能创建 `edge_labels` 中定义的谓词边。
- `shared_property_types` 是属性值结构模板，不是 node label。
- `ontology_role_decisions`、audit、source_inputs、experiment guidance 都不是 final schema contract，不应进入下游抽取 prompt 的 schema 主体。
