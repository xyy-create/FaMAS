const DEFAULT_KB_NAME = ['Default', 'KB'].join(' ')

export const displayValueLabels = {
  active: '启用',
  admin: '管理员',
  beishida: '北师大版',
  biology: '生物',
  chemistry: '化学',
  chinese: '语文',
  compulsory: '必修',
  document: '文档',
  english: '英语',
  geography: '地理',
  high_school: '高中',
  history: '历史',
  image: '图片',
  junior_high: '初中',
  limited: '依据有限',
  mathematics: '数学',
  matched: '已匹配',
  node: '节点',
  none: '无',
  pep: '人教版',
  physics: '物理',
  primary_school: '小学',
  private: '私有',
  public: '公开',
  renjiao: '人教版',
  source: '来源',
  selective_compulsory: '选择性必修',
  sujiao: '苏教版',
  sufficient: '依据充分',
  tongbian: '统编版',
  triple: '三元组',
  user: '普通用户',
  yuelu: '岳麓版',
  architectural: '建筑',
  cancelled: '已取消',
  degraded: '降级完成',
  discussion_question: '讨论题',
  failed: '失败',
  fallback: '预览',
  no_graph: '无图谱',
  no_matches: '无匹配',
  pending: '等待中',
  processed: '已处理图谱',
  reflection_prompt: '思考题',
  running: '运行中',
  success: '成功',
  unknown: '未知',
}

const internalValueLabels = Object.fromEntries(
  Object.entries(displayValueLabels).map(([key, value]) => [value, key]),
)

export const predicateLabels = {
  associated_with: '关联',
  associated_with_culture: '关联文化',
  belonged_to: '曾属于',
  belongs_to: '属于',
  belongs_to_period: '属于时期',
  characterized_by: '特征为',
  classified_as: '归类为',
  composed_of: '由此组成',
  contains: '包含',
  defines: '定义',
  defined_as: '定义为',
  exemplifies: '举例说明',
  exhibits: '展示',
  exhibits_trait: '体现特征',
  extends: '延伸',
  formed_by: '形成于',
  has_property: '具有性质',
  influencedBy: '受影响于',
  integrates: '整合',
  located_at: '位于',
  located_in: '位于',
  part_of: '属于',
  precedes: '早于',
  produces: '产生',
  prerequisite_for: '作为先修',
  requires: '依赖',
  tests: '考查',
  uses_method: '使用方法',
  related: '相关',
}

export const typeLabels = {
  ArchaeologicalCulture: '考古文化',
  ArchaeologicalSite: '考古遗址',
  ChapterSection: '章节',
  ChemicalCategory: '化学类别',
  ChemicalSubstance: '化学物质',
  ChronologicalPeriod: '历史时期',
  Element: '元素',
  FossilSpecimen: '化石标本',
  HomininFossilFind: '古人类化石发现',
  HomininPopulation: '古人类群体',
  HistoricalEvent: '历史事件',
  HistoricalFigure: '历史人物',
  HistoricalFormation: '历史形成',
  HistoricalPeriod: '历史时期',
  HistoricalProcess: '历史进程',
  KnowledgePoint: '知识点',
  ActivityUnit: '活动单元',
  BuddhismLocalizationInChina: '佛教中国化',
  ChineseCulturalConcept: '中华文化概念',
  ChineseIntellectualSchool: '中国思想流派',
  ClassificationCategory: '分类类别',
  CurriculumUnit: '课程单元',
  FourGreatInventions: '四大发明',
  IntegrativeUnit: '综合单元',
  Node: '节点',
  Problem: '题目',
  RitualInstitution: '礼仪制度',
  SocioculturalSystem: '社会文化制度',
  ZhongXiHuiTong: '中西会通',
  Figure: '图片',
  Image: '图片',
  Source: '来源',
  Triple: '三元组',
}

export const evidenceKindLabels = {
  image: '图片',
  node: '节点',
  source: '来源',
  triple: '关系',
  图片: '图片',
  节点: '节点',
  来源: '来源',
  关系: '关系',
}

export function displayKnowledgeBaseName(name) {
  if (!name || name === DEFAULT_KB_NAME) return '默认知识库'
  return name
}

export function displayValue(value) {
  const text = String(value ?? '').trim()
  if (!text) return ''
  return text
    .split(/\s*,\s*/)
    .map((part) => displayValueLabels[part] || part)
    .join('，')
}

export function displayEvidenceKind(kind) {
  const text = String(kind ?? '').trim()
  return evidenceKindLabels[text] || displayValueLabels[text] || text
}

export function localizeInlineText(value) {
  let text = String(value ?? '').trim()
  if (!text) return ''
  Object.entries(predicateLabels).forEach(([key, label]) => {
    text = text.replaceAll(key, label)
  })
  Object.entries(typeLabels).forEach(([key, label]) => {
    text = text.replaceAll(key, label)
  })
  Object.entries(displayValueLabels).forEach(([key, label]) => {
    text = text.replaceAll(key, label)
  })
  return text
}

export function hasChinese(text) {
  return /[\u4e00-\u9fff]/.test(String(text || ''))
}

export function looksLikeEnglishSentence(text) {
  const value = String(text || '').trim()
  if (!value) return false
  const asciiLetters = (value.match(/[A-Za-z]/g) || []).length
  const chineseChars = (value.match(/[\u4e00-\u9fff]/g) || []).length
  const words = (value.match(/[A-Za-z]{2,}/g) || []).length
  return asciiLetters >= 16 && words >= 3 && chineseChars === 0
}

export function chineseFirst(...values) {
  for (const value of values) {
    const text = localizeInlineText(value)
    if (hasChinese(text)) return text
  }
  for (const value of values) {
    const text = localizeInlineText(value)
    if (text && !looksLikeEnglishSentence(text)) return text
  }
  return ''
}

export function normalizeDisplayInput(value) {
  const text = String(value ?? '').trim()
  if (!text) return ''
  return internalValueLabels[text] || text
}

export function displayMetadataText(...values) {
  return values.map(displayValue).filter(Boolean).join(' / ') || '-'
}

export function displayPredicateLabel(predicate) {
  return predicateLabels[predicate] || displayValueLabels[predicate] || '关系'
}

export function displayTypeLabel(type) {
  return typeLabels[type] || displayValueLabels[type] || '节点'
}
