const DATA_ROOTS = {
  en: "./data/en",
  zh: "./data/zh",
};
const IMAGE_DATA_DIR = "./assets";
const API_CONFIG = getApiConfig();
const ANNOTATION_TAGS = [
  "重点",
  "难点",
  "易错点",
  "考点",
  "图片证据",
  "适合课堂讲解",
  "适合问答引用",
  "需人工复核",
  "已确认",
  "错误抽取",
];

const state = {
  language: "zh",
  nodes: [],
  edges: [],
  triples: [],
  meta: {},
  currentUser: null,
  annotationTemplates: [],
  nodeById: new Map(),
  edgeById: new Map(),
  selected: null,
  hovered: null,
  focusNodeId: null,
  minimapSearch: "",
  minimapHoveredNodeId: null,
  minimapPulseUntil: 0,
  graphRefreshJobId: null,
  graphRefreshTimer: null,
  graphRefreshMessage: "",
  leftCollapsed: false,
  explorerCollapsed: false,
  explorerExpanded: false,
  expandedRect: null,
  minimapWindowResize: null,
  detailCollapsed: true,
  detailHeight: 300,
  previousDetailHeight: 260,
  search: "",
  predicate: "all",
  view: { x: 0, y: 0, scale: 1, rotation: 0 },
  alpha: 1,
  size: { width: 0, height: 0, dpr: 1 },
  pointer: { x: 0, y: 0 },
  drag: null,
  detailResize: null,
  minimapDrag: null,
};

const els = {
  appShell: document.querySelector(".app-shell"),
  graphPanel: document.querySelector(".graph-panel"),
  graphStage: document.querySelector(".graph-stage"),
  leftPanel: document.querySelector(".triples-panel"),
  leftPanelToggle: document.querySelector("#leftPanelToggle"),
  stats: document.querySelector("#stats"),
  searchInput: document.querySelector("#searchInput"),
  predicateFilter: document.querySelector("#predicateFilter"),
  clearFocusButton: document.querySelector("#clearFocusButton"),
  focusChip: document.querySelector("#focusChip"),
  tripleList: document.querySelector("#tripleList"),
  legend: document.querySelector("#legend"),
  canvasWrap: document.querySelector(".canvas-wrap"),
  canvas: document.querySelector("#graphCanvas"),
  minimapCanvasWrap: document.querySelector("#minimapCanvasWrap"),
  minimapCanvas: document.querySelector("#minimapCanvas"),
  minimapLegend: document.querySelector("#minimapLegend"),
  hoverCard: document.querySelector("#hoverCard"),
  detailPanel: document.querySelector("#detailPanel"),
  detailResizer: document.querySelector("#detailResizer"),
  explorerPanel: document.querySelector("#explorerPanel"),
  explorerToggle: document.querySelector("#explorerToggle"),
  minimapExpandButton: document.querySelector("#minimapExpandButton"),
  minimapOverlayBackdrop: document.querySelector("#minimapOverlayBackdrop"),
  explorerMapView: document.querySelector("#explorerMapView"),
  minimapSearchInput: document.querySelector("#minimapSearchInput"),
  imageModal: document.querySelector("#imageModal"),
  imageModalClose: document.querySelector("#imageModalClose"),
  imageModalImg: document.querySelector("#imageModalImg"),
  imageModalTitle: document.querySelector("#imageModalTitle"),
  imageModalDescription: document.querySelector("#imageModalDescription"),
  imageModalMeta: document.querySelector("#imageModalMeta"),
  zoomInButton: document.querySelector("#zoomInButton"),
  zoomOutButton: document.querySelector("#zoomOutButton"),
  rotateLeftButton: document.querySelector("#rotateLeftButton"),
  rotateRightButton: document.querySelector("#rotateRightButton"),
  resetButton: document.querySelector("#resetButton"),
  detailToggle: document.querySelector("#detailToggle"),
};

const ctx = els.canvas.getContext("2d");
const minimapCtx = els.minimapCanvas.getContext("2d");

const I18N = {
  en: {
    documentTitle: "Chemistry Knowledge Graph Triple Visualization",
    kgTriples: "知识三元组",
    appTitle: "Chemistry Knowledge Graph",
    genericDocumentTitle: "Knowledge Graph Triple Visualization",
    genericAppTitle: "知识图谱",
    grade: "Grade",
    gradeValue: "Senior Grade 1",
    subject: "Subject",
    subjectValue: "Chemistry",
    textbook: "Textbook",
    textbookValue: "Senior High School Chemistry Compulsory Volume 1",
    textbookVersion: "Textbook Version",
    textbookVersionValue: "Not specified in current data",
    searchPlaceholder: "Search chapters, knowledge points, evidence",
    relationFilter: "Relation filter",
    allRelations: "All relations",
    clearFocus: "Clear focus",
    tripleList: "Triple list",
    graphControls: "Graph controls",
    zoomOut: "Zoom out",
    zoomIn: "Zoom in",
    rotateLeft: "Rotate counterclockwise",
    rotateRight: "Rotate clockwise",
    reset: "Reset",
    collapseDetail: "Collapse detail panel",
    expandDetail: "Expand detail panel",
    collapseLeft: "Collapse left panel",
    expandLeft: "Expand left panel",
    collapsePanel: "Collapse panel",
    expandPanel: "Expand panel",
    expandMinimap: "Expand minimap",
    restoreMinimap: "Restore minimap",
    resizeDetail: "Resize detail panel height",
    minimapPanel: "Global graph minimap navigator",
    minimapTitle: "Global Minimap Navigator",
    minimapSearchPlaceholder: "Search and highlight nodes",
    minimapHint: "Drag the minimap background to pan the main graph; hover a node to see its direct neighbors; click to center and select it.",
    subjectInfo: "Subject information",
    relationOut: "Outgoing",
    relationIn: "Incoming",
    imageDetail: "Image detail",
    close: "Close",
    figurePreview: "图片预览",
    statsTriples: "Triples",
    statsNodes: "Nodes",
    statsEdges: "Edges",
    focusPrefix: "Focus",
    noTriples: "No matching triples",
    dataset: "Dataset",
    knowledgeBase: "Knowledge Base",
    documentScope: "Document Scope",
    allDocuments: "All Documents",
    generatedFromUpload: "Generated from uploaded PDF data",
    source: "Source",
    backendGenerated: "Backend Generated",
    publisherField: "Publisher",
    notSpecified: "Not specified",
    chemistry: "Chemistry",
    overviewTitle: "Graph Overview",
    overviewText: "This view shows triple relations from Senior High School Chemistry Compulsory Volume 1.",
    genericOverviewText: "This view shows triple relations generated from the selected uploaded PDF data.",
    relatedTriples: "Related triples",
    subjectField: "Subject",
    predicateField: "Relation",
    objectField: "Object",
    edgeId: "Edge ID",
    noImage: "No image",
    figureEvidence: "Figure evidence",
    noFigureDescription: "No accompanying description",
    figureId: "Figure ID",
    relationsUnit: "relations",
    readFailed: "Failed to load",
    openHttpHint: "Please open this page through the local HTTP server.",
    typeLabels: {
      ChapterSection: "Chapter",
      KnowledgePoint: "Knowledge Point",
      Problem: "Problem",
      Node: "Node",
    },
    predicateLabels: {
      belongs_to: "Belongs to",
      classified_as: "Classified as",
      contains: "Contains",
      exhibits: "Exhibits",
      exhibits_trait: "Exhibits trait",
      precedes: "Precedes",
      requires: "Requires",
      tests: "Tests",
    },
    fieldNames: {
      title: "Title",
      name: "Name",
      definition: "Definition",
      description: "Description",
      chapter_num: "Chapter No.",
      aliases: "Aliases",
      rationale: "Rationale",
      problem_type: "Problem Type",
      answer: "Answer",
      formula: "Formula",
      state_at_STP: "State at STP",
      source_path: "Source Path",
      web_source_document_name: "Source Document",
      figure_id: "Figure ID",
    },
  },
  zh: {
    documentTitle: "化学知识图谱三元组可视化",
    kgTriples: "三元组",
    appTitle: "化学知识图谱",
    genericDocumentTitle: "知识图谱三元组可视化",
    genericAppTitle: "知识图谱",
    grade: "年级",
    gradeValue: "高一",
    subject: "学科",
    subjectValue: "化学",
    textbook: "教材",
    textbookValue: "普通高中教科书·化学必修第一册",
    textbookVersion: "教材版本",
    textbookVersionValue: "当前数据未标注",
    searchPlaceholder: "搜索章节、知识点、证据",
    relationFilter: "关系筛选",
    allRelations: "全部关系",
    clearFocus: "清除聚焦",
    tripleList: "三元组列表",
    graphControls: "图谱控制",
    zoomOut: "缩小",
    zoomIn: "放大",
    rotateLeft: "逆时针旋转",
    rotateRight: "顺时针旋转",
    reset: "重置",
    collapseDetail: "折叠详情栏",
    expandDetail: "展开详情栏",
    collapseLeft: "折叠左侧栏",
    expandLeft: "展开左侧栏",
    collapsePanel: "折叠面板",
    expandPanel: "展开面板",
    expandMinimap: "放大缩略图",
    restoreMinimap: "还原缩略图",
    resizeDetail: "调整详情面板高度",
    minimapPanel: "图谱全局缩略导航图",
    minimapTitle: "全局缩略导航图",
    minimapSearchPlaceholder: "检索并高亮节点",
    minimapHint: "拖动缩略图背景可平移主图谱；悬停节点可查看直接相邻关系；点击节点可居中并选中。",
    subjectInfo: "学科基本信息",
    relationOut: "出向",
    relationIn: "入向",
    imageDetail: "图片详情",
    close: "关闭",
    figurePreview: "图片预览",
    statsTriples: "三元组",
    statsNodes: "节点",
    statsEdges: "边",
    focusPrefix: "聚焦",
    noTriples: "没有匹配的三元组",
    dataset: "数据集",
    knowledgeBase: "知识库",
    documentScope: "文档范围",
    allDocuments: "全部文档",
    generatedFromUpload: "由上传的 PDF 数据生成",
    source: "来源",
    backendGenerated: "后端生成",
    chemistry: "化学",
    overviewTitle: "图谱概览",
    overviewText: "当前展示《普通高中教科书·化学必修第一册》的三元组关系。",
    genericOverviewText: "当前展示从所选上传 PDF 数据生成的三元组关系。",
    relatedTriples: "相关三元组",
    subjectField: "主体",
    predicateField: "关系",
    objectField: "客体",
    edgeId: "边 ID",
    noImage: "暂无图片",
    figureEvidence: "图像证据",
    noFigureDescription: "暂无配套介绍信息",
    figureId: "图像 ID",
    relationsUnit: "条关系",
    readFailed: "读取失败",
    openHttpHint: "请通过本地 HTTP 服务打开页面。",
    typeLabels: {
      ArchaeologicalCulture: "考古文化",
      ArchaeologicalSite: "考古遗址",
      ChapterSection: "章节",
      ChemicalCategory: "化学类别",
      ChemicalSubstance: "化学物质",
      ChronologicalPeriod: "历史时期",
      Element: "元素",
      FossilSpecimen: "化石标本",
      HomininFossilFind: "古人类化石发现",
      HomininPopulation: "古人类群体",
      HistoricalEvent: "历史事件",
      HistoricalFigure: "历史人物",
      HistoricalFormation: "历史形成",
      HistoricalPeriod: "历史时期",
      HistoricalProcess: "历史进程",
      KnowledgePoint: "知识点",
      ActivityUnit: "活动单元",
      BuddhismLocalizationInChina: "佛教中国化",
      ChineseCulturalConcept: "中华文化概念",
      ChineseIntellectualSchool: "中国思想流派",
      ClassificationCategory: "分类类别",
      CurriculumUnit: "课程单元",
      FourGreatInventions: "四大发明",
      IntegrativeUnit: "综合单元",
      Problem: "题目",
      RitualInstitution: "礼仪制度",
      SocioculturalSystem: "社会文化制度",
      ZhongXiHuiTong: "中西会通",
      Node: "节点",
    },
    predicateLabels: {
      associated_with: "关联",
      associated_with_culture: "关联文化",
      belonged_to: "曾属于",
      belongs_to: "属于",
      belongs_to_period: "属于时期",
      characterized_by: "特征为",
      classified_as: "归类为",
      composed_of: "由此组成",
      contains: "包含",
      defines: "定义",
      defined_as: "定义为",
      exemplifies: "举例说明",
      exhibits: "展示",
      exhibits_trait: "体现特征",
      extends: "延伸",
      formed_by: "形成于",
      has_property: "具有性质",
      influencedBy: "受影响于",
      integrates: "整合",
      located_at: "位于",
      located_in: "位于",
      part_of: "属于",
      precedes: "早于",
      produces: "产生",
      prerequisite_for: "作为先修",
      related: "相关",
      requires: "依赖",
      tests: "考查",
      uses_method: "使用方法",
    },
    fieldNames: {
      title: "标题",
      name: "名称",
      definition: "定义",
      description: "描述",
      chapter_num: "章节号",
      section_num: "课节号",
      site_name: "遗址名称",
      period_name: "时期名称",
      culture_name: "文化名称",
      system_name: "制度名称",
      substance_name: "物质名称",
      element_name: "元素名称",
      specimen_name: "标本名称",
      event_name: "事件名称",
      figure_name: "人物名称",
      location: "地点",
      cultural_affiliation: "文化归属",
      chronological_range: "年代范围",
      key_features: "主要特征",
      defining_traits: "定义特征",
      defining_characteristics: "典型特征",
      material_signature: "器物特征",
      subsistence_base: "生计方式",
      start_year_bce_ce: "开始年代",
      end_year_bce_ce: "结束年代",
      type_site: "典型遗址",
      key_events: "关键事件",
      aliases: "别名",
      rationale: "依据",
      problem_type: "题型",
      answer: "答案",
      formula: "化学式",
      state_at_STP: "标准状态",
      state: "状态",
      source_path: "来源路径",
      web_source_document_name: "来源文档",
      figure_id: "图像 ID",
      classification_axis: "分类轴",
      classification_criterion: "分类标准",
      relation_label: "关系标签",
      taxon: "分类学名称",
      discovery_site: "发现地点",
      discovery_location: "发现地点",
      discovery_date: "发现时间",
      date_range: "年代范围",
      age_estimate: "年代估计",
      time_span: "时间跨度",
      time_span_bce: "公元前年代",
      time_range_bce: "公元前范围",
      geographic_range: "地理范围",
      distribution_region: "分布区域",
      core_region: "核心区域",
      diagnostic_traits: "识别特征",
      behavioral_evidence: "行为证据",
      morphological_features: "形态特征",
      key_artifacts: "关键器物",
      typical_artifacts: "典型器物",
      defining_artifacts: "代表器物",
      historical_period: "历史时期",
      historical_evolution: "历史演变",
      modern_relevance: "现代意义",
      semantic_evolution: "语义演变",
      classical_source: "经典来源",
      classical_sources: "经典来源",
      founders: "代表人物",
      core_doctrines: "核心主张",
      rules: "规则",
      spatial_rules: "空间规则",
      stages: "阶段",
      contribution: "贡献",
      characteristics: "特征",
      pedagogical_goal: "教学目标",
      type_of_influence: "影响类型",
      evidence_features: "证据特征",
      core_principle: "核心原则",
      historical_exponents: "历史代表",
      contrasting_positions: "对比立场",
      key_agents: "关键主体",
      exemplar_forms: "代表形式",
    },
  },
};

const typeStyle = {
  ChapterSection: {
    color: "#256d7b",
    fill: "#dceff2",
    radius: 22,
  },
  KnowledgePoint: {
    color: "#3f7b42",
    fill: "#e2f0df",
    radius: 15,
  },
  Problem: {
    color: "#9a6424",
    fill: "#f4e8d8",
    radius: 14,
  },
  Node: {
    color: "#616c65",
    fill: "#edf1ee",
    radius: 14,
  },
};

const predicateStyle = {
  contains: "#256d7b",
  requires: "#3f7b42",
  tests: "#9a6424",
};

const displayValueLabels = {
  active: "启用",
  admin: "管理员",
  beishida: "北师大版",
  biology: "生物",
  chemistry: "化学",
  chinese: "语文",
  compulsory: "必修",
  document: "文档",
  english: "英语",
  geography: "地理",
  high_school: "高中",
  history: "历史",
  image: "图片",
  junior_high: "初中",
  limited: "依据有限",
  mathematics: "数学",
  matched: "已匹配",
  node: "节点",
  none: "无",
  pep: "人教版",
  physics: "物理",
  primary_school: "小学",
  private: "私有",
  public: "公开",
  renjiao: "人教版",
  source: "来源",
  selective_compulsory: "选择性必修",
  sujiao: "苏教版",
  sufficient: "依据充分",
  tongbian: "统编版",
  triple: "三元组",
  user: "普通用户",
  yuelu: "岳麓版",
  architectural: "建筑",
  cancelled: "已取消",
  degraded: "降级完成",
  discussion_question: "讨论题",
  failed: "失败",
  fallback: "预览",
  matched: "已匹配",
  no_graph: "无图谱",
  no_matches: "无匹配",
  pending: "等待中",
  processed: "已处理图谱",
  reflection_prompt: "思考题",
  running: "运行中",
  success: "成功",
  true: "是",
  false: "否",
  unknown: "未知",
};

const nodeTitleKeys = [
  "title",
  "display_name",
  "name",
  "site_name",
  "period_name",
  "culture_name",
  "system_name",
  "substance_name",
  "element_name",
  "specimen_name",
  "event_name",
  "figure_name",
  "problem_text",
  "question",
  "description",
];

const blockedNodeFields = new Set([
  "source_path",
  "web_source_document_id",
  "confidence",
  "revision_round",
  "status",
  "audit_refs",
  "evidence",
]);

const blockedEdgeFields = new Set([
  "confidence",
  "web_source_document_id",
  "revision_round",
  "status",
  "audit_refs",
  "original_edge_ids",
  "evidence",
]);

init();

async function init() {
  try {
    bindEvents();
    state.currentUser = await loadCurrentUser();
    await loadLanguageData(state.language);
    renderStaticUi();
    renderTripleList();
    renderMinimapLegend();
    renderDetail();
    collapseDetailPanel();
    resizeCanvas();
    requestAnimationFrame(tick);
  } catch (error) {
    showLoadError(error);
  }
}

async function loadLanguageData(language) {
  const dataRoot = DATA_ROOTS[language] || DATA_ROOTS.en;
  const previousPositions = new Map(
    state.nodes.map((node) => [
      node.id,
      { x: node.x, y: node.y, vx: node.vx, vy: node.vy, fixed: node.fixed },
    ]),
  );
  const [tripleData, nodeData, edgeData] = await Promise.all([
    loadJson(getDataUrl(language, dataRoot, "triples.json")),
    loadJson(getDataUrl(language, dataRoot, "merged_nodes.json")),
    loadJson(getDataUrl(language, dataRoot, "merged_edges.json")),
  ]);
  const [meta, annotationTemplates] = await Promise.all([
    loadGraphMetadata(),
    loadAnnotationTemplates(),
  ]);
  state.meta = meta;
  state.annotationTemplates = annotationTemplates;
  state.nodeById = new Map();
  state.edgeById = new Map();
  buildModel(tripleData, nodeData, edgeData);
  for (const node of state.nodes) {
    const previous = previousPositions.get(node.id);
    if (!previous) continue;
    Object.assign(node, previous);
  }
}

async function loadCurrentUser() {
  if (!API_CONFIG.enabled) return null;
  const response = await fetch(new URL("/api/auth/me", API_CONFIG.apiBase).toString(), { headers: apiHeaders() });
  if (!response.ok) return null;
  return response.json();
}

async function loadAnnotationTemplates() {
  if (!API_CONFIG.enabled) return [];
  const response = await fetch(new URL("/api/knowledge-graph/annotation-templates", API_CONFIG.apiBase).toString(), {
    headers: apiHeaders(),
  });
  if (!response.ok) return [];
  const value = await response.json();
  return Array.isArray(value) ? value.map(normalizeAnnotationTemplate).filter(Boolean) : [];
}

async function loadJson(url) {
  const response = await fetch(url, { headers: apiHeaders() });
  if (!response.ok) {
    throw new Error(`${url} ${t("readFailed")}: ${response.status}`);
  }
  return response.json();
}

async function loadGraphMetadata() {
  if (!API_CONFIG.enabled) return {};
  const apiUrl = new URL("/api/knowledge-graph/summary", API_CONFIG.apiBase);
  apiUrl.searchParams.set("knowledge_base_id", API_CONFIG.knowledgeBaseId);
  if (API_CONFIG.documentId) {
    apiUrl.searchParams.set("document_id", API_CONFIG.documentId);
  }
  const response = await fetch(apiUrl.toString(), { headers: apiHeaders() });
  if (!response.ok) return {};
  const summary = await response.json();
  return {
    knowledgeBaseName: summary.knowledge_base_name || "",
    documentName: summary.documents?.length === 1 ? summary.documents[0].filename : "",
    subject: summary.metadata?.subject || "",
    grade: summary.metadata?.grade || "",
    publisher: summary.metadata?.publisher || "",
    textbook: summary.metadata?.textbook || "",
    textbookVersion: summary.metadata?.textbook_version || "",
  };
}

function apiHeaders() {
  const headers = {};
  if (API_CONFIG.enabled) {
    const token = window.localStorage.getItem("famas_admin_token");
    if (token) {
      headers.Authorization = `Bearer ${token}`;
    }
  }
  return headers;
}

function getApiConfig() {
  const params = new URLSearchParams(window.location.search);
  return {
    enabled: params.get("api") === "1",
    apiBase: params.get("apiBase") || window.location.origin,
    knowledgeBaseId: params.get("knowledge_base_id") || "",
    documentId: params.get("document_id") || "",
  };
}

function getDataUrl(language, dataRoot, filename) {
  if (!API_CONFIG.enabled) {
    return `${dataRoot}/${filename}`;
  }
  const apiUrl = new URL(
    `/api/knowledge-graph/${language}/${filename}`,
    API_CONFIG.apiBase,
  );
  apiUrl.searchParams.set("knowledge_base_id", API_CONFIG.knowledgeBaseId);
  if (API_CONFIG.documentId) {
    apiUrl.searchParams.set("document_id", API_CONFIG.documentId);
  }
  return apiUrl.toString();
}

function getImageUrl(imagePath) {
  const apiUrl = new URL("/api/knowledge-graph/image", API_CONFIG.apiBase);
  const token = window.localStorage.getItem("famas_admin_token");
  apiUrl.searchParams.set("knowledge_base_id", API_CONFIG.knowledgeBaseId);
  apiUrl.searchParams.set("image_path", imagePath);
  if (token) {
    apiUrl.searchParams.set("access_token", token);
  }
  if (API_CONFIG.documentId) {
    apiUrl.searchParams.set("document_id", API_CONFIG.documentId);
  }
  return apiUrl.toString();
}

function t(key) {
  return I18N[state.language]?.[key] || I18N.en[key] || key;
}

function getTypeLabel(type) {
  if (state.language === "zh") {
    return I18N.zh.typeLabels?.[type] || displayValueLabels[type] || "节点";
  }
  return I18N.en.typeLabels[type] || humanizeIdentifier(type);
}

function getPredicateLabel(predicate) {
  if (state.language === "zh") {
    return I18N.zh.predicateLabels?.[predicate] || displayValueLabels[predicate] || "关系";
  }
  return I18N[state.language]?.predicateLabels?.[predicate]
    || I18N.en.predicateLabels?.[predicate]
    || humanizeIdentifier(predicate);
}

function getFieldName(key) {
  if (state.language === "zh") {
    return I18N.zh.fieldNames?.[key] || displayValueLabels[key] || "字段";
  }
  return I18N.en.fieldNames[key] || humanizeIdentifier(key);
}

function applyStaticTranslations() {
  document.documentElement.lang = state.language === "zh" ? "zh-CN" : "en";
  document.title = apiModeValue("genericDocumentTitle", "documentTitle");
  document.querySelectorAll("[data-i18n]").forEach((element) => {
    element.textContent = translatedStaticValue(element.dataset.i18n);
  });
  document.querySelectorAll("[data-i18n-placeholder]").forEach((element) => {
    element.placeholder = t(element.dataset.i18nPlaceholder);
  });
  document.querySelectorAll("[data-i18n-title]").forEach((element) => {
    element.title = t(element.dataset.i18nTitle);
  });
  document.querySelectorAll("[data-i18n-aria-label]").forEach((element) => {
    element.setAttribute("aria-label", t(element.dataset.i18nAriaLabel));
  });
  refreshPanelToggleLabels();
}

function translatedStaticValue(key) {
  if (!API_CONFIG.enabled) {
    return t(key);
  }
  const apiValues = {
    appTitle: apiModeValue("genericAppTitle", "appTitle"),
    grade: t("subject"),
    gradeValue: metadataValue("subject"),
    subject: t("grade"),
    subjectValue: metadataValue("grade"),
    textbook: t("textbook"),
    textbookValue: textbookMetadataValue(),
    textbookVersion: t("publisherField"),
    textbookVersionValue: metadataValue("publisher"),
  };
  return Object.hasOwn(apiValues, key) ? apiValues[key] : t(key);
}

function apiModeValue(apiKey, staticKey) {
  return API_CONFIG.enabled ? t(apiKey) : t(staticKey);
}

function metadataValue(key) {
  return localizeDisplayValue(state.meta?.[key]) || t("notSpecified");
}

function textbookMetadataValue() {
  const textbook = localizeDisplayValue(state.meta?.textbook || "");
  const version = localizeDisplayValue(state.meta?.textbookVersion || "");
  if (textbook && version) return `${textbook} (${version})`;
  return textbook || version || t("notSpecified");
}

function buildModel(tripleData, nodeData, edgeData) {
  const rawNodes = nodeData.nodes || [];
  const rawEdges = edgeData.edges || [];
  const rawTriples = tripleData.triples || [];

  state.nodes = rawNodes.map((raw, index) => {
    const props = raw.properties || {};
    const type = raw.label || "Node";
    const style = typeStyle[type] || typeStyle.Node;
    const angle = (Math.PI * 2 * index) / Math.max(rawNodes.length, 1);
    const ring = type === "ChapterSection" ? 160 : type === "Problem" ? 340 : 250;
    const node = {
      id: raw.node_id,
      type,
      title: getNodeTitle(raw),
      raw,
      props: sanitizeFields(props, blockedNodeFields),
      annotations: normalizeAnnotation(props.web_annotations),
      evidence: extractQuotes(props.evidence),
      figures: normalizeFigures(props.figures),
      radius: style.radius,
      x: Math.cos(angle) * ring + typeBias(type),
      y: Math.sin(angle) * ring,
      vx: 0,
      vy: 0,
      degree: 0,
    };
    state.nodeById.set(node.id, node);
    return node;
  });

  state.edges = rawEdges
    .map((raw) => {
      const source = state.nodeById.get(raw.source_node_id);
      const target = state.nodeById.get(raw.target_node_id);
      if (!source || !target) return null;

      source.degree += 1;
      target.degree += 1;

      const props = raw.properties || {};
      const edge = {
        id: raw.edge_id,
        predicate: raw.predicate || "related",
        source,
        target,
        raw,
        props: sanitizeFields(props, blockedEdgeFields),
        annotations: normalizeAnnotation(props.web_annotations),
        evidence: extractQuotes(props.evidence),
        figures: normalizeFigures(props.figures),
      };
      state.edgeById.set(edge.id, edge);
      return edge;
    })
    .filter(Boolean);

  state.triples = rawTriples.map((raw) => {
    const subject = state.nodeById.get(raw.subject_node_id);
    const object = state.nodeById.get(raw.object_node_id);
    const edge = state.edgeById.get(raw.edge_id);
    if (edge) edge.tripleId = raw.triple_id;
    return {
      id: raw.triple_id,
      subject,
      object,
      edge,
      edgeId: raw.edge_id,
      predicate: raw.predicate || edge?.predicate || "related",
      annotations: normalizeAnnotation(raw.properties?.web_annotations || edge?.annotations),
      evidence: extractQuotes(raw.evidence),
      raw,
    };
  });
}

function bindEvents() {
  els.searchInput.addEventListener("input", (event) => {
    state.search = event.target.value.trim().toLowerCase();
    renderTripleList();
    pulseMinimapMatches();
    drawMinimap();
    state.alpha = Math.max(state.alpha, 0.18);
  });

  els.predicateFilter.addEventListener("change", (event) => {
    state.predicate = event.target.value;
    renderTripleList();
    drawMinimap();
  });

  els.clearFocusButton.addEventListener("click", () => {
    state.focusNodeId = null;
    state.selected = null;
    renderTripleList();
    renderMinimapLegend();
    renderDetail();
    drawMinimap();
  });

  els.tripleList.addEventListener("click", (event) => {
    const item = event.target.closest(".triple-item");
    if (!item) return;
    selectTriple(item.dataset.tripleId);
  });

  els.leftPanelToggle.addEventListener("click", toggleLeftPanel);
  els.detailPanel.addEventListener("click", (event) => {
    const figure = event.target.closest(".figure-card.interactive");
    if (!figure) return;
    openImageModal({
      src: figure.dataset.figureSrc,
      title: figure.dataset.figureTitle,
      description: figure.dataset.figureDescription,
      figureId: figure.dataset.figureId,
      imagePath: figure.dataset.figureImagePath,
      targetId: figure.dataset.figureTargetId,
    });
  });

  els.explorerToggle.addEventListener("click", toggleExplorer);
  els.minimapExpandButton.addEventListener("click", toggleExpandedMinimap);
  els.minimapOverlayBackdrop.addEventListener("click", restoreExpandedMinimap);
  els.explorerPanel.addEventListener("pointerdown", onMinimapPanelResizeStart);
  els.explorerPanel.addEventListener("pointermove", onMinimapPanelResizeMove);
  els.explorerPanel.addEventListener("pointerup", onMinimapPanelResizeEnd);
  els.explorerPanel.addEventListener("pointercancel", onMinimapPanelResizeEnd);
  els.explorerPanel.addEventListener("lostpointercapture", onMinimapPanelResizeEnd);
  els.minimapSearchInput.addEventListener("input", (event) => {
    state.minimapSearch = event.target.value.trim().toLowerCase();
    pulseMinimapMatches();
    drawMinimap();
  });
  els.minimapCanvas.addEventListener("pointerdown", onMinimapPointerDown);
  els.minimapCanvas.addEventListener("pointermove", onMinimapPointerMove);
  els.minimapCanvas.addEventListener("pointerup", onMinimapPointerUp);
  els.minimapCanvas.addEventListener("pointercancel", onMinimapPointerCancel);
  els.minimapCanvas.addEventListener("pointerleave", onMinimapPointerLeave);

  els.detailResizer.addEventListener("pointerdown", onDetailResizeStart);

  els.imageModalClose.addEventListener("click", closeImageModal);
  els.imageModal.addEventListener("click", (event) => {
    if (event.target.dataset.modalClose !== undefined) closeImageModal();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    if (!els.imageModal.hidden) {
      closeImageModal();
      return;
    }
    if (state.explorerExpanded) restoreExpandedMinimap();
  });
  window.addEventListener("beforeunload", stopGraphRefreshPolling);
  window.addEventListener("resize", onMinimapWindowResize);

  els.zoomInButton.addEventListener("click", () => zoomAtCenter(1.18));
  els.zoomOutButton.addEventListener("click", () => zoomAtCenter(0.85));
  els.rotateLeftButton.addEventListener("click", () => rotateGraph(-Math.PI / 18));
  els.rotateRightButton.addEventListener("click", () => rotateGraph(Math.PI / 18));
  els.resetButton.addEventListener("click", resetView);
  els.detailToggle.addEventListener("click", toggleDetailPanel);
  els.canvas.addEventListener("wheel", onWheel, { passive: false });
  els.canvas.addEventListener("pointerdown", onPointerDown);
  els.canvas.addEventListener("pointermove", onPointerMove);
  els.canvas.addEventListener("pointerup", onPointerUp);
  els.canvas.addEventListener("pointerleave", onPointerLeave);

  new ResizeObserver(resizeCanvas).observe(els.canvasWrap);
  new ResizeObserver(resizeMinimap).observe(els.minimapCanvasWrap);
}

function renderStaticUi() {
  applyStaticTranslations();
  els.stats.innerHTML = `${state.triples.length} ${t("statsTriples")}<br>${state.nodes.length} ${t("statsNodes")}<br>${state.edges.length} ${t("statsEdges")}`;

  const predicates = [...new Set(state.edges.map((edge) => edge.predicate))];
  els.predicateFilter.innerHTML = [
    `<option value="all">${escapeHtml(t("allRelations"))}</option>`,
    ...predicates.map((predicate) => `<option value="${escapeHtml(predicate)}">${escapeHtml(getPredicateLabel(predicate))}</option>`),
  ].join("");
  els.predicateFilter.value = state.predicate;

  const typeCounts = state.nodes.reduce((acc, node) => {
    acc[node.type] = (acc[node.type] || 0) + 1;
    return acc;
  }, {});

  els.legend.innerHTML = Object.entries(typeCounts)
    .map(([type, count]) => {
      const style = typeStyle[type] || typeStyle.Node;
      return `<span class="legend-item"><i class="dot" style="background:${style.color}"></i>${escapeHtml(getTypeLabel(type))} ${count}</span>`;
    })
    .join("");
}

function renderTripleList() {
  const triples = getFilteredTriples();
  const focusNode = state.focusNodeId ? state.nodeById.get(state.focusNodeId) : null;

  if (focusNode) {
    els.focusChip.hidden = false;
    els.focusChip.textContent = `${t("focusPrefix")}: ${focusNode.title}`;
  } else {
    els.focusChip.hidden = true;
    els.focusChip.textContent = "";
  }

  if (!triples.length) {
    els.tripleList.innerHTML = `<div class="empty-state">${escapeHtml(t("noTriples"))}</div>`;
    return;
  }

  els.tripleList.innerHTML = triples
    .map((triple) => {
      const active = state.selected?.kind === "triple" && state.selected.id === triple.id;
      const subject = triple.subject?.title || triple.raw.subject_node_id;
      const object = triple.object?.title || triple.raw.object_node_id;
      const predicateLabel = getPredicateLabel(triple.predicate);
      const quote = displayText(firstText(triple.evidence) || firstText(triple.edge?.evidence) || "");
      return `
        <button class="triple-item ${active ? "active" : ""}" type="button" data-triple-id="${escapeHtml(triple.id)}">
          <div class="triple-main">
            <strong>${escapeHtml(subject)}</strong>
            <span class="triple-arrow">${escapeHtml(predicateLabel)}</span>
            <strong>${escapeHtml(object)}</strong>
          </div>
          <div class="triple-meta">
            <span class="badge ${escapeHtml(triple.predicate)}">${escapeHtml(predicateLabel)}</span>
            <span>${quote ? escapeHtml(truncate(quote, 28)) : escapeHtml(triple.edgeId || "")}</span>
          </div>
        </button>
      `;
    })
    .join("");
}

function renderMinimapLegend() {
  const nodeTypes = [...new Set(state.nodes.map((node) => node.type))];
  const predicates = [...new Set(state.edges.map((edge) => edge.predicate))];
  els.minimapLegend.innerHTML = [
    ...(API_CONFIG.enabled
      ? []
      : [`<span class="minimap-legend-item"><i class="dot" style="background:#4b74a8"></i>${escapeHtml(t("chemistry"))}</span>`]),
    ...nodeTypes.map((type) => {
      const style = typeStyle[type] || typeStyle.Node;
      return `<span class="minimap-legend-item"><i class="dot" style="background:${style.color}"></i>${escapeHtml(getTypeLabel(type))}</span>`;
    }),
    ...predicates.map((predicate) => {
      const color = predicateStyle[predicate] || "#8d9890";
      return `<span class="minimap-legend-item"><i class="line-swatch" style="background:${color}"></i>${escapeHtml(getPredicateLabel(predicate))}</span>`;
    }),
  ].join("");
}

function getFilteredTriples() {
  return state.triples.filter((triple) => {
    if (state.predicate !== "all" && triple.predicate !== state.predicate) return false;
    if (state.focusNodeId) {
      const hit = triple.subject?.id === state.focusNodeId || triple.object?.id === state.focusNodeId;
      if (!hit) return false;
    }
    if (!state.search) return true;
    return searchableText(triple).includes(state.search);
  });
}

function renderDetail() {
  if (!state.selected) {
    els.detailPanel.innerHTML = `
      <div class="detail-grid">
        <div>
          <h2>${escapeHtml(t("overviewTitle"))}</h2>
          <p>${escapeHtml(apiModeValue("genericOverviewText", "overviewText"))}</p>
          <div class="kv">
            <div class="kv-row"><span>${escapeHtml(t("statsTriples"))}</span><strong>${state.triples.length}</strong></div>
            <div class="kv-row"><span>${escapeHtml(t("statsNodes"))}</span><strong>${state.nodes.length}</strong></div>
            <div class="kv-row"><span>${escapeHtml(t("statsEdges"))}</span><strong>${state.edges.length}</strong></div>
          </div>
        </div>
        <div>${renderPredicateSummary()}</div>
      </div>
      ${renderCreateOverrideForms()}
    `;
    bindCreateOverrideForms();
    return;
  }

  if (state.selected.kind === "node") {
    renderNodeDetail(state.nodeById.get(state.selected.id));
  } else if (state.selected.kind === "edge") {
    renderEdgeDetail(state.edgeById.get(state.selected.id));
  } else if (state.selected.kind === "triple") {
    renderTripleDetail(state.triples.find((triple) => triple.id === state.selected.id));
  }
}

function renderNodeDetail(node) {
  if (!node) return;
  const related = state.triples.filter((triple) => triple.subject?.id === node.id || triple.object?.id === node.id);
  els.detailPanel.innerHTML = `
    <div class="detail-grid">
      <div>
        <h2>${escapeHtml(node.title)}</h2>
        <p><span class="badge">${escapeHtml(getTypeLabel(node.type))}</span></p>
        ${renderAnnotationBadges(node.annotations)}
        ${renderKeyValues(node.props)}
        ${renderQuotes(node.evidence)}
        <p>${escapeHtml(t("relatedTriples"))}: ${related.length}</p>
      </div>
      <div>${renderFigures(node.figures)}</div>
    </div>
    ${renderAnnotationForm("node", node.id, node.annotations)}
    ${renderOverrideForm("node", node.id, {
      title: node.title,
      label: node.type,
      description: node.props.description || node.props.definition || "",
      sourceContextId: node.raw.source_context_id || "",
    })}
  `;
  bindAnnotationForm("node", node.id, els.detailPanel);
  bindOverrideForm("node", node.id);
}

function renderEdgeDetail(edge) {
  if (!edge) return;
  els.detailPanel.innerHTML = `
    <div class="detail-grid">
      <div>
        <h2>${escapeHtml(edge.source.title)} → ${escapeHtml(edge.target.title)}</h2>
        <p><span class="badge ${escapeHtml(edge.predicate)}">${escapeHtml(getPredicateLabel(edge.predicate))}</span></p>
        ${renderAnnotationBadges(edge.annotations)}
        ${renderKeyValues(edge.props)}
        ${renderQuotes(edge.evidence)}
      </div>
      <div>${renderFigures(edge.figures)}</div>
    </div>
    ${renderAnnotationForm("edge", edge.id, edge.annotations)}
    ${renderOverrideForm("edge", edge.id, {
      predicate: edge.predicate,
      sourceNodeId: edge.source.id,
      targetNodeId: edge.target.id,
      relationDescription: edge.props.rationale || "",
      sourceContextId: edge.raw.source_context_id || "",
    })}
  `;
  bindAnnotationForm("edge", edge.id, els.detailPanel);
  bindOverrideForm("edge", edge.id);
}

function renderTripleDetail(triple) {
  if (!triple) return;
  const figures = mergeFigures(triple.edge?.figures, triple.subject?.figures, triple.object?.figures);
  const quotes = triple.evidence.length ? triple.evidence : triple.edge?.evidence || [];
  els.detailPanel.innerHTML = `
    <div class="detail-grid">
      <div>
        <h2>${escapeHtml(triple.subject?.title || "")} → ${escapeHtml(triple.object?.title || "")}</h2>
        <p><span class="badge ${escapeHtml(triple.predicate)}">${escapeHtml(getPredicateLabel(triple.predicate))}</span></p>
        ${renderAnnotationBadges(triple.annotations)}
        <div class="kv">
          <div class="kv-row"><span>${escapeHtml(t("subjectField"))}</span><strong>${escapeHtml(triple.subject?.title || triple.raw.subject_node_id)}</strong></div>
          <div class="kv-row"><span>${escapeHtml(t("predicateField"))}</span><strong>${escapeHtml(getPredicateLabel(triple.predicate))}</strong></div>
          <div class="kv-row"><span>${escapeHtml(t("objectField"))}</span><strong>${escapeHtml(triple.object?.title || triple.raw.object_node_id)}</strong></div>
          <div class="kv-row"><span>${escapeHtml(t("edgeId"))}</span><strong>${escapeHtml(triple.edgeId || "")}</strong></div>
        </div>
        ${renderQuotes(quotes)}
      </div>
      <div>${renderFigures(figures)}</div>
    </div>
    ${triple.edgeId ? renderAnnotationForm("edge", triple.edgeId, triple.edge?.annotations || triple.annotations) : ""}
  `;
  if (triple.edgeId) bindAnnotationForm("edge", triple.edgeId, els.detailPanel);
}

function renderCreateOverrideForms() {
  if (!API_CONFIG.enabled) return "";
  if (!API_CONFIG.documentId) {
    return `
      <section class="override-panel">
        <h3>新增节点 / 关系</h3>
        <p class="override-note">当前为全部文档视图。请先在上方切换到单个 PDF，再新增节点或关系。</p>
      </section>
    `;
  }
  const nodeOptions = state.nodes
    .map((node) => `<option value="${escapeHtml(node.id)}">${escapeHtml(truncate(node.title, 40))}</option>`)
    .join("");
  return `
    <section class="override-create-grid">
      <form class="override-panel" data-create-override="node">
        <div class="override-head">
          <div>
            <h3>新增节点</h3>
            <p>用于补充自动抽取遗漏的知识点。</p>
          </div>
        </div>
        <div class="override-grid">
          <label><span>节点名称</span><input name="title" type="text" required /></label>
          <label><span>节点类型</span><input name="label" type="text" value="KnowledgePoint" /></label>
          <label class="wide"><span>节点描述</span><textarea name="description" rows="2"></textarea></label>
          <label><span>章节 / 来源说明</span><input name="source_note" type="text" /></label>
          <label><span>重要程度</span><input name="importance" type="text" /></label>
          <label class="wide"><span>用户补充证据说明</span><textarea name="user_evidence" rows="2"></textarea></label>
        </div>
        <div class="override-actions">
          <button class="text-button" type="submit">新增节点</button>
          <span data-override-status></span>
        </div>
      </form>

      <form class="override-panel" data-create-override="edge">
        <div class="override-head">
          <div>
            <h3>新增关系</h3>
            <p>主体和客体必须来自当前图谱已有节点或用户新增节点。</p>
          </div>
        </div>
        <div class="override-grid">
          <label><span>主体节点</span><select name="source_node_id" required>${nodeOptions}</select></label>
          <label><span>客体节点</span><select name="target_node_id" required>${nodeOptions}</select></label>
          <label><span>关系类型</span><input name="predicate" type="text" value="related_to" required /></label>
          <label><span>重要程度</span><input name="importance" type="text" /></label>
          <label class="wide"><span>关系说明</span><textarea name="relation_description" rows="2"></textarea></label>
          <label class="wide"><span>用户补充证据说明</span><textarea name="user_evidence" rows="2"></textarea></label>
        </div>
        <div class="override-actions">
          <button class="text-button" type="submit">新增关系</button>
          <span data-override-status></span>
        </div>
      </form>
    </section>
  `;
}

function bindCreateOverrideForms() {
  els.detailPanel.querySelectorAll("[data-create-override]").forEach((form) => {
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      await createOverrideItem(form, form.dataset.createOverride);
    });
  });
}

async function createOverrideItem(form, kind) {
  const status = form.querySelector("[data-override-status]");
  if (status) status.textContent = "创建中...";
  const payload = {
    knowledge_base_id: Number(API_CONFIG.knowledgeBaseId),
    document_id: Number(API_CONFIG.documentId),
    source_context_ids: collectCreateOverrideSourceContextIds(form, kind),
  };
  for (const element of form.querySelectorAll("input[name], textarea[name], select[name]")) {
    const value = element.value.trim();
    if (value) payload[element.name] = value;
  }
  try {
    const response = await fetch(
      `${API_CONFIG.apiBase}/api/knowledge-graph/overrides/${kind === "edge" ? "edges" : "nodes"}`,
      {
        method: "POST",
        headers: { ...apiHeaders(), "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      },
    );
    if (!response.ok) throw new Error(`创建失败：${response.status}`);
    const created = await response.json();
    if (status) status.textContent = "已创建";
    form.reset();
    await loadLanguageData(state.language);
    state.selected = { kind: created.item_kind, id: created.item_id };
    renderStaticUi();
    renderTripleList();
    renderMinimapLegend();
    renderDetail();
    await queueGraphRefreshAfterOverride(kind, created.item_id, response, status);
  } catch (error) {
    if (status) status.textContent = error.message || "创建失败";
  }
}

function renderAnnotationForm(kind, targetId, annotation = {}) {
  if (!API_CONFIG.enabled) return "";
  if (!API_CONFIG.documentId) {
    return `
      <section class="annotation-panel">
        <h3>人工标注</h3>
        <p class="override-note">当前为全部文档视图。请先切换到单个 PDF，再标注节点、关系或图片。</p>
      </section>
    `;
  }
  const normalized = normalizeAnnotation(annotation);
  const selectedTags = new Set(normalized.tags);
  const templates = annotationTemplatesForKind(kind);
  return `
    <form class="annotation-panel" data-annotation-kind="${escapeHtml(kind)}" data-annotation-id="${escapeHtml(targetId)}">
      <div class="override-head">
        <div>
          <h3>${escapeHtml(annotationTitle(kind))}</h3>
          <p>标注用于整理教学重点，并会影响问答检索时的证据排序。</p>
        </div>
      </div>
      ${
        templates.length
          ? `
            <label class="annotation-template-select">
              <span>套用模板</span>
              <select name="annotation_template">
                <option value="">选择公共模板</option>
                ${templates.map((template) => `<option value="${escapeHtml(String(template.id))}">${escapeHtml(template.name)}</option>`).join("")}
              </select>
            </label>
          `
          : ""
      }
      <div class="annotation-tags">
        ${ANNOTATION_TAGS.map((tag) => `
          <label>
            <input name="tags" type="checkbox" value="${escapeHtml(tag)}" ${selectedTags.has(tag) ? "checked" : ""} />
            <span>${escapeHtml(tag)}</span>
          </label>
        `).join("")}
      </div>
      <label class="annotation-note">
        <span>标注说明</span>
        <textarea name="note" rows="2" placeholder="可记录教学用途、修订原因或复核意见">${escapeHtml(normalized.note || "")}</textarea>
      </label>
      ${
        state.currentUser?.role === "admin"
          ? `
            <div class="annotation-template-save">
              <input name="template_name" type="text" placeholder="公共模板名称" />
              <button class="text-button" type="button" data-template-save>保存为公共模板</button>
            </div>
          `
          : ""
      }
      <div class="override-actions">
        <button class="text-button" type="submit">保存标注</button>
        <button class="text-button" type="button" data-annotation-reset>清除标注</button>
        <span data-annotation-status></span>
      </div>
    </form>
  `;
}

function bindAnnotationForm(kind, targetId, root = document) {
  const form = root.querySelector(`[data-annotation-kind="${cssEscape(kind)}"][data-annotation-id="${cssEscape(targetId)}"]`);
  if (!form) return;
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    await saveAnnotationForm(form, kind, targetId);
  });
  form.querySelector("[data-annotation-reset]")?.addEventListener("click", async () => {
    await deleteAnnotation(kind, targetId, form);
  });
  form.elements.annotation_template?.addEventListener("change", () => {
    applyAnnotationTemplate(form, Number(form.elements.annotation_template.value));
  });
  form.querySelector("[data-template-save]")?.addEventListener("click", async () => {
    await saveAnnotationTemplate(form, kind);
  });
}

async function saveAnnotationForm(form, kind, targetId) {
  const status = form.querySelector("[data-annotation-status]");
  if (status) status.textContent = "保存中...";
  const payload = {
    knowledge_base_id: Number(API_CONFIG.knowledgeBaseId),
    document_id: Number(API_CONFIG.documentId),
    tags: [...form.querySelectorAll('input[name="tags"]:checked')].map((input) => input.value),
    note: form.elements.note?.value?.trim() || "",
  };
  try {
    const response = await fetch(
      `${API_CONFIG.apiBase}/api/knowledge-graph/annotations/${encodeURIComponent(kind)}/${encodeURIComponent(targetId)}`,
      {
        method: "PUT",
        headers: { ...apiHeaders(), "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      },
    );
    if (!response.ok) throw new Error(`保存失败：${response.status}`);
    if (status) status.textContent = "已保存";
    await reloadGraphAfterAnnotation(kind, targetId);
  } catch (error) {
    if (status) status.textContent = error.message || "保存失败";
  }
}

async function deleteAnnotation(kind, targetId, form) {
  const status = form.querySelector("[data-annotation-status]");
  if (status) status.textContent = "清除中...";
  const params = new URLSearchParams({
    knowledge_base_id: API_CONFIG.knowledgeBaseId,
    document_id: API_CONFIG.documentId,
  });
  try {
    const response = await fetch(
      `${API_CONFIG.apiBase}/api/knowledge-graph/annotations/${encodeURIComponent(kind)}/${encodeURIComponent(targetId)}?${params.toString()}`,
      { method: "DELETE", headers: apiHeaders() },
    );
    if (!response.ok) throw new Error(`清除失败：${response.status}`);
    if (status) status.textContent = "已清除";
    await reloadGraphAfterAnnotation(kind, targetId);
  } catch (error) {
    if (status) status.textContent = error.message || "清除失败";
  }
}

async function reloadGraphAfterAnnotation(kind, targetId) {
  await loadLanguageData(state.language);
  if (kind === "node" && state.nodeById.has(targetId)) {
    state.selected = { kind: "node", id: targetId };
  } else if (kind === "edge" && state.edgeById.has(targetId)) {
    state.selected = { kind: "edge", id: targetId };
  }
  renderStaticUi();
  renderTripleList();
  renderMinimapLegend();
  renderDetail();
}

function applyAnnotationTemplate(form, templateId) {
  const template = state.annotationTemplates.find((item) => item.id === templateId);
  if (!template) return;
  const tags = new Set(template.tags);
  form.querySelectorAll('input[name="tags"]').forEach((input) => {
    input.checked = tags.has(input.value);
  });
  if (form.elements.note && template.note) {
    form.elements.note.value = template.note;
  }
}

async function saveAnnotationTemplate(form, kind) {
  const status = form.querySelector("[data-annotation-status]");
  const name = form.elements.template_name?.value?.trim() || "";
  if (!name) {
    if (status) status.textContent = "请先填写模板名称";
    return;
  }
  if (status) status.textContent = "模板保存中...";
  const payload = {
    target_kind: kind,
    name,
    tags: [...form.querySelectorAll('input[name="tags"]:checked')].map((input) => input.value),
    note: form.elements.note?.value?.trim() || "",
  };
  try {
    const response = await fetch(`${API_CONFIG.apiBase}/api/knowledge-graph/annotation-templates`, {
      method: "POST",
      headers: { ...apiHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!response.ok) throw new Error(`模板保存失败：${response.status}`);
    state.annotationTemplates = await loadAnnotationTemplates();
    if (status) status.textContent = "模板已保存";
    renderDetail();
  } catch (error) {
    if (status) status.textContent = error.message || "模板保存失败";
  }
}

function annotationTemplatesForKind(kind) {
  return state.annotationTemplates.filter((template) => template.targetKind === kind);
}

function renderAnnotationBadges(annotation = {}) {
  const normalized = normalizeAnnotation(annotation);
  if (!normalized.tags.length && !normalized.note) return "";
  return `
    <div class="annotation-summary">
      ${normalized.tags.map((tag) => `<span>${escapeHtml(tag)}</span>`).join("")}
      ${normalized.note ? `<p>${escapeHtml(normalized.note)}</p>` : ""}
    </div>
  `;
}

function annotationTitle(kind) {
  if (kind === "node") return "节点标注";
  if (kind === "edge") return "关系标注";
  return "图片标注";
}

function renderOverrideForm(kind, itemId, values = {}) {
  if (!API_CONFIG.enabled) return "";
  if (!API_CONFIG.documentId) {
    return `
      <section class="override-panel">
        <h3>人工修正</h3>
        <p class="override-note">当前为全部文档视图。请先在上方切换到单个 PDF，再修改节点或关系。</p>
      </section>
    `;
  }
  const isNode = kind === "node";
  return `
    <form
      class="override-panel"
      data-override-kind="${escapeHtml(kind)}"
      data-override-id="${escapeHtml(itemId)}"
      data-source-context-id="${escapeHtml(values.sourceContextId || "")}"
    >
      <div class="override-head">
        <div>
          <h3>${isNode ? "节点修正" : "关系修正"}</h3>
          <p>修正只保存在 Web 数据库中，不会覆盖原始知识图谱文件。</p>
        </div>
        <label class="override-hide">
          <input name="is_hidden" type="checkbox" />
          <span>删除</span>
        </label>
      </div>
      <div class="override-grid">
        ${
          isNode
            ? `
              <label><span>节点名称</span><input name="title" type="text" value="${escapeHtml(values.title || "")}" /></label>
              <label><span>节点类型</span><input name="label" type="text" value="${escapeHtml(values.label || "")}" /></label>
              <label class="wide"><span>节点描述</span><textarea name="description" rows="2">${escapeHtml(values.description || "")}</textarea></label>
            `
            : `
              <label><span>关系类型</span><input name="predicate" type="text" value="${escapeHtml(values.predicate || "")}" /></label>
              <label><span>主体节点 ID</span><input name="source_node_id" type="text" value="${escapeHtml(values.sourceNodeId || "")}" /></label>
              <label><span>客体节点 ID</span><input name="target_node_id" type="text" value="${escapeHtml(values.targetNodeId || "")}" /></label>
              <label class="wide"><span>关系说明</span><textarea name="relation_description" rows="2">${escapeHtml(values.relationDescription || "")}</textarea></label>
            `
        }
        <label><span>章节 / 来源说明</span><input name="source_note" type="text" /></label>
        <label><span>重要程度</span><input name="importance" type="text" placeholder="如：重点 / 难点 / 一般" /></label>
        <label><span>学科标签</span><input name="subject_tag" type="text" /></label>
        <label><span>证据可信度</span><input name="evidence_confidence" type="text" placeholder="如：已确认 / 需复核" /></label>
        <label class="wide"><span>关联图片路径</span><textarea name="image_paths" rows="2" placeholder="一行一个图片路径，例如：images/page008_img002.jpg"></textarea></label>
        <label class="wide"><span>用户补充证据说明</span><textarea name="user_evidence" rows="2"></textarea></label>
        <label class="wide"><span>备注</span><textarea name="note" rows="2"></textarea></label>
      </div>
      <div class="override-actions">
        <button class="text-button" type="submit">保存修正</button>
        <button class="text-button" type="button" data-override-reset>清除修正</button>
        <span data-override-status></span>
      </div>
    </form>
  `;
}

function bindOverrideForm(kind, itemId) {
  const form = els.detailPanel.querySelector(`[data-override-kind="${cssEscape(kind)}"][data-override-id="${cssEscape(itemId)}"]`);
  if (!form) return;
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    await saveOverrideForm(form, kind, itemId);
  });
  form.querySelector("[data-override-reset]")?.addEventListener("click", async () => {
    await deleteOverride(kind, itemId, form);
  });
}

async function saveOverrideForm(form, kind, itemId) {
  const status = form.querySelector("[data-override-status]");
  if (status) status.textContent = "保存中...";
  const payload = {
    knowledge_base_id: Number(API_CONFIG.knowledgeBaseId),
    document_id: Number(API_CONFIG.documentId),
    is_hidden: Boolean(form.elements.is_hidden?.checked),
    patch: {},
    source_context_ids: collectOverrideSourceContextIds(kind, itemId, form),
  };
  for (const element of form.querySelectorAll("input[name], textarea[name]")) {
    if (element.name === "is_hidden") continue;
    const value = element.value.trim();
    if (!value) continue;
    if (element.name === "image_paths") {
      payload.patch.image_paths = value
        .split(/[\n,，]/)
        .map((item) => item.trim())
        .filter(Boolean);
    } else {
      payload.patch[element.name] = value;
    }
  }
  try {
    const response = await fetch(
      `${API_CONFIG.apiBase}/api/knowledge-graph/overrides/${encodeURIComponent(kind)}/${encodeURIComponent(itemId)}`,
      {
        method: "PUT",
        headers: { ...apiHeaders(), "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      },
    );
    if (!response.ok) throw new Error(`保存失败：${response.status}`);
    if (status) status.textContent = "已保存，页面已更新，后台正在重构图谱...";
    await reloadGraphAfterOverride(kind, itemId);
    await queueGraphRefreshAfterOverride(kind, itemId, response, status);
  } catch (error) {
    if (status) status.textContent = error.message || "保存失败";
  }
}

async function deleteOverride(kind, itemId, form) {
  const status = form.querySelector("[data-override-status]");
  if (status) status.textContent = "清除中...";
  const params = new URLSearchParams({
    knowledge_base_id: API_CONFIG.knowledgeBaseId,
    document_id: API_CONFIG.documentId,
  });
  for (const sourceContextId of collectOverrideSourceContextIds(kind, itemId, form)) {
    params.append("source_context_ids", sourceContextId);
  }
  try {
    const response = await fetch(
      `${API_CONFIG.apiBase}/api/knowledge-graph/overrides/${encodeURIComponent(kind)}/${encodeURIComponent(itemId)}?${params.toString()}`,
      { method: "DELETE", headers: apiHeaders() },
    );
    if (!response.ok) throw new Error(`清除失败：${response.status}`);
    if (status) status.textContent = "已清除，页面已更新，后台正在重构图谱...";
    await reloadGraphAfterOverride(kind, itemId);
    await queueGraphRefreshAfterOverride(kind, itemId, response, status);
  } catch (error) {
    if (status) status.textContent = error.message || "清除失败";
  }
}

async function queueGraphRefreshAfterOverride(kind, itemId, response, statusEl = null) {
  if (!API_CONFIG.documentId) {
    await reloadGraphAfterOverride(kind, itemId);
    return;
  }

  try {
    const headerJobId = Number(response?.headers?.get("X-Graph-Refresh-Job-Id") || 0);
    state.graphRefreshJobId = headerJobId || (await findActiveGraphRefreshJobId()) || null;
    state.graphRefreshMessage = "图谱正在后台重构，完成后会自动刷新。";
    if (state.graphRefreshJobId) {
      stopGraphRefreshPolling();
      startGraphRefreshPolling(kind, itemId, statusEl, state.graphRefreshJobId);
      if (statusEl) statusEl.textContent = state.graphRefreshMessage;
      return;
    }
    if (statusEl) statusEl.textContent = "页面已更新";
  } catch (error) {
    state.graphRefreshMessage = "";
    if (statusEl) statusEl.textContent = error.message || "图谱重构任务启动失败";
    await reloadGraphAfterOverride(kind, itemId);
  }
}

function collectCreateOverrideSourceContextIds(form, kind) {
  const sourceContextIds = new Set();
  const addContextId = (value) => {
    const contextId = String(value || "").trim();
    if (contextId) {
      sourceContextIds.add(contextId);
    }
  };
  if (kind === "edge") {
    const sourceNodeId = String(form.elements.source_node_id?.value || "").trim();
    const targetNodeId = String(form.elements.target_node_id?.value || "").trim();
    addContextId(state.nodeById.get(sourceNodeId)?.raw.source_context_id);
    addContextId(state.nodeById.get(targetNodeId)?.raw.source_context_id);
  }
  if (!sourceContextIds.size && form?.dataset.sourceContextId) {
    addContextId(form.dataset.sourceContextId);
  }
  return [...sourceContextIds];
}

function collectOverrideSourceContextIds(kind, itemId, form = null) {
  const sourceContextIds = new Set();
  const addContextId = (value) => {
    const contextId = String(value || "").trim();
    if (contextId) {
      sourceContextIds.add(contextId);
    }
  };
  const addNodeNeighborhood = (node) => {
    if (!node) return;
    addContextId(node.raw.source_context_id);
    for (const edge of state.edges) {
      if (edge.source.id !== node.id && edge.target.id !== node.id) continue;
      addContextId(edge.raw.source_context_id);
      addContextId(edge.source.raw.source_context_id);
      addContextId(edge.target.raw.source_context_id);
    }
  };

  if (kind === "node") {
    addNodeNeighborhood(state.nodeById.get(itemId));
  } else if (kind === "edge") {
    const edge = state.edgeById.get(itemId);
    if (edge) {
      addNodeNeighborhood(edge.source);
      addNodeNeighborhood(edge.target);
      addContextId(edge.raw.source_context_id);
    }
    const sourceNodeId = String(form?.elements.source_node_id?.value || "").trim();
    const targetNodeId = String(form?.elements.target_node_id?.value || "").trim();
    addNodeNeighborhood(state.nodeById.get(sourceNodeId));
    addNodeNeighborhood(state.nodeById.get(targetNodeId));
  }

  if (!sourceContextIds.size && form?.dataset.sourceContextId) {
    addContextId(form.dataset.sourceContextId);
  }
  return [...sourceContextIds];
}

async function findActiveGraphRefreshJobId() {
  if (!API_CONFIG.documentId) return null;
  const response = await fetch(
    `${API_CONFIG.apiBase}/api/documents/${encodeURIComponent(API_CONFIG.documentId)}/jobs`,
    { headers: apiHeaders() },
  );
  if (!response.ok) return null;
  const jobs = await response.json();
  if (!Array.isArray(jobs)) return null;
  const activeJob = jobs.find(
    (job) =>
      (job.stage === "build_graph" || job.stage === "full_pipeline") &&
      (job.status === "pending" || job.status === "running"),
  );
  return activeJob?.id ?? null;
}

function startGraphRefreshPolling(kind, itemId, statusEl = null, jobId = null) {
  if (!API_CONFIG.documentId) return;
  if (jobId) {
    state.graphRefreshJobId = jobId;
  }
  stopGraphRefreshPolling();
  state.graphRefreshTimer = window.setInterval(async () => {
    try {
      const jobsResponse = await fetch(
        `${API_CONFIG.apiBase}/api/documents/${encodeURIComponent(API_CONFIG.documentId)}/jobs`,
        { headers: apiHeaders() },
      );
      if (!jobsResponse.ok) {
        return;
      }
      const jobs = await jobsResponse.json();
      const currentJob = Array.isArray(jobs)
        ? jobs.find((job) => job.id === state.graphRefreshJobId)
        : null;
      if (!currentJob) {
        return;
      }
      if (currentJob.status === "pending" || currentJob.status === "running") {
        if (statusEl) statusEl.textContent = "图谱正在后台重构，完成后会自动刷新。";
        return;
      }
      stopGraphRefreshPolling();
      state.graphRefreshJobId = null;
      state.graphRefreshMessage = "";
      if (currentJob.status === "success" || currentJob.status === "degraded") {
        if (statusEl) statusEl.textContent = "图谱已更新";
        await reloadGraphAfterOverride(kind, itemId);
        return;
      }
      if (statusEl) statusEl.textContent = `图谱重构失败：${currentJob.error_message || "未知错误"}`;
    } catch {
      return;
    }
  }, 4000);
}

function stopGraphRefreshPolling() {
  if (state.graphRefreshTimer) {
    window.clearInterval(state.graphRefreshTimer);
    state.graphRefreshTimer = null;
  }
}

async function reloadGraphAfterOverride(kind, itemId) {
  await loadLanguageData(state.language);
  if (kind === "node" && state.nodeById.has(itemId)) {
    state.selected = { kind: "node", id: itemId };
  } else if (kind === "edge" && state.edgeById.has(itemId)) {
    state.selected = { kind: "edge", id: itemId };
  } else {
    state.selected = null;
    state.focusNodeId = null;
  }
  renderStaticUi();
  renderTripleList();
  renderMinimapLegend();
  renderDetail();
}

function cssEscape(value) {
  if (window.CSS?.escape) return window.CSS.escape(value);
  return String(value).replaceAll('"', '\\"');
}

function renderPredicateSummary() {
  const counts = state.edges.reduce((acc, edge) => {
    acc[edge.predicate] = (acc[edge.predicate] || 0) + 1;
    return acc;
  }, {});
  return `
    <div class="kv">
      ${Object.entries(counts)
        .map(([predicate, count]) => `<div class="kv-row"><span>${escapeHtml(getPredicateLabel(predicate))}</span><strong>${count}</strong></div>`)
        .join("")}
    </div>
  `;
}

function renderKeyValues(props) {
  const entries = Object.entries(props || {})
    .map(([key, value]) => [key, formatFieldValue(key, value)])
    .filter(([, value]) => hasValue(value));
  if (!entries.length) return "";
  return `
    <div class="kv">
      ${entries
        .map(([key, value]) => {
          const label = getFieldName(key);
          return `<div class="kv-row"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`;
        })
        .join("")}
    </div>
  `;
}

function renderQuotes(quotes) {
  const filtered = (quotes || []).map(displayText).filter(Boolean);
  if (!filtered.length) return "";
  return filtered
    .slice(0, 3)
    .map((quote) => `<p class="preview-text">${escapeHtml(quote)}</p>`)
    .join("");
}

function renderFigures(figures) {
  const list = (figures || []).filter((figure) => figure.src);
  if (!list.length) return `<p class="preview-subtitle">${escapeHtml(t("noImage"))}</p>`;
  return `
    <div class="figure-strip">
      ${list
        .slice(0, 4)
        .map((figure) => {
          const title = displayText(figure.name) || t("figureEvidence");
          const description = displayText(figure.description) || title || t("figureEvidence");
          return `
            <button class="figure-card interactive" type="button"
              data-figure-src="${escapeHtml(figure.src)}"
              data-figure-title="${escapeHtml(title)}"
              data-figure-description="${escapeHtml(figure.description || t("noFigureDescription"))}"
              data-figure-id="${escapeHtml(figure.figureId || "")}"
              data-figure-image-path="${escapeHtml(figure.imagePath || "")}"
              data-figure-target-id="${escapeHtml(figure.targetId || "")}">
              <img src="${escapeHtml(figure.src)}" alt="${escapeHtml(description)}" />
              <p>${escapeHtml(truncate(description, 70))}</p>
              ${renderAnnotationBadges(figure.annotations)}
            </button>
          `;
        })
        .join("")}
    </div>
  `;
}

function selectTriple(tripleId) {
  const triple = state.triples.find((item) => item.id === tripleId);
  if (!triple) return;
  state.selected = { kind: "triple", id: triple.id };
  state.focusNodeId = null;
  if (state.detailCollapsed) expandDetailPanel();
  centerOnNodes([triple.subject, triple.object].filter(Boolean));
  renderTripleList();
  drawMinimap();
  renderDetail();
}

function selectNode(node) {
  state.selected = { kind: "node", id: node.id };
  state.focusNodeId = node.id;
  if (state.detailCollapsed) expandDetailPanel();
  renderTripleList();
  drawMinimap();
  renderDetail();
}

function selectEdge(edge) {
  state.selected = { kind: "edge", id: edge.id };
  state.focusNodeId = null;
  if (state.detailCollapsed) expandDetailPanel();
  renderTripleList();
  drawMinimap();
  renderDetail();
}

function locateNode(nodeId) {
  const node = state.nodeById.get(nodeId);
  if (!node) return;
  selectNode(node);
  centerOnNodes([node]);
}

function locateEdge(edgeId) {
  const edge = state.edgeById.get(edgeId);
  if (!edge) return;
  selectEdge(edge);
  centerOnNodes([edge.source, edge.target]);
}

function toggleExplorer() {
  if (state.explorerExpanded) {
    restoreExpandedMinimap({ returnFocus: false });
  }
  setExplorerCollapsed(!state.explorerCollapsed);
  resizeCanvas();
  if (!state.explorerCollapsed) {
    requestAnimationFrame(resizeMinimap);
  }
}

function setExplorerCollapsed(collapsed) {
  state.explorerCollapsed = Boolean(collapsed);
  els.graphPanel.classList.toggle("is-explorer-collapsed", state.explorerCollapsed);
  els.explorerPanel.classList.toggle("is-collapsed", state.explorerCollapsed);
  refreshPanelToggleLabels();
}

function toggleExpandedMinimap() {
  if (state.explorerExpanded) {
    restoreExpandedMinimap();
  } else {
    expandMinimap();
  }
}

function expandMinimap() {
  if (state.explorerCollapsed) {
    setExplorerCollapsed(false);
  }

  const limits = getExpandedLimits();
  const initialRect = state.expandedRect || MinimapHelpers.createInitialPanelRect(limits);
  state.expandedRect = MinimapHelpers.constrainPanelRect(initialRect, limits);
  state.explorerExpanded = true;
  els.graphPanel.classList.add("is-explorer-expanded");
  els.explorerPanel.classList.add("is-expanded");
  els.explorerPanel.setAttribute("role", "dialog");
  els.explorerPanel.setAttribute("aria-modal", "true");
  els.minimapOverlayBackdrop.hidden = false;
  applyExpandedPanelRect(state.expandedRect);
  refreshPanelToggleLabels();
  requestAnimationFrame(() => {
    resizeCanvas();
    resizeMinimap();
  });
}

function restoreExpandedMinimap(options = {}) {
  const returnFocus = options.returnFocus !== false;
  if (!state.explorerExpanded) return;

  finishMinimapPanelResize();
  state.explorerExpanded = false;
  els.graphPanel.classList.remove("is-explorer-expanded");
  els.explorerPanel.classList.remove("is-expanded");
  els.explorerPanel.removeAttribute("role");
  els.explorerPanel.removeAttribute("aria-modal");
  els.minimapOverlayBackdrop.hidden = true;
  for (const property of ["left", "top", "width", "height"]) {
    els.explorerPanel.style.removeProperty(property);
  }
  refreshPanelToggleLabels();
  requestAnimationFrame(() => {
    resizeCanvas();
    resizeMinimap();
  });
  if (returnFocus) {
    els.minimapExpandButton.focus({ preventScroll: true });
  }
}

function getExpandedLimits() {
  const width = Math.max(0, window.innerWidth || document.documentElement.clientWidth || 0);
  const height = Math.max(0, window.innerHeight || document.documentElement.clientHeight || 0);
  const margin = Math.min(12, width / 2, height / 2);
  return { width, height, margin, minWidth: 520, minHeight: 420 };
}

function applyExpandedPanelRect(rect) {
  els.explorerPanel.style.left = `${rect.left}px`;
  els.explorerPanel.style.top = `${rect.top}px`;
  els.explorerPanel.style.width = `${rect.width}px`;
  els.explorerPanel.style.height = `${rect.height}px`;
}

function onMinimapWindowResize() {
  if (!state.explorerExpanded) return;
  finishMinimapPanelResize();
  const limits = getExpandedLimits();
  const storedRect = state.expandedRect || MinimapHelpers.createInitialPanelRect(limits);
  state.expandedRect = MinimapHelpers.constrainPanelRect(storedRect, limits);
  applyExpandedPanelRect(state.expandedRect);
  requestAnimationFrame(resizeMinimap);
}

function onMinimapPanelResizeStart(event) {
  const handle = event.target.closest("[data-minimap-resize]");
  if (!state.explorerExpanded || !handle || !els.explorerPanel.contains(handle) || event.button !== 0) return;

  event.preventDefault();
  const bounds = els.explorerPanel.getBoundingClientRect();
  const startRect = MinimapHelpers.constrainPanelRect(
    { left: bounds.left, top: bounds.top, width: bounds.width, height: bounds.height },
    getExpandedLimits(),
  );
  state.expandedRect = startRect;
  applyExpandedPanelRect(startRect);
  state.minimapWindowResize = {
    pointerId: event.pointerId,
    startX: event.clientX,
    startY: event.clientY,
    startRect,
    direction: handle.dataset.minimapResize,
    handle,
  };
  handle.setPointerCapture(event.pointerId);
  requestAnimationFrame(resizeMinimap);
}

function onMinimapPanelResizeMove(event) {
  const resize = state.minimapWindowResize;
  if (!resize || event.pointerId !== resize.pointerId) return;

  event.preventDefault();
  state.expandedRect = MinimapHelpers.resizePanelRect(
    resize.startRect,
    { x: event.clientX - resize.startX, y: event.clientY - resize.startY },
    resize.direction,
    getExpandedLimits(),
  );
  applyExpandedPanelRect(state.expandedRect);
  requestAnimationFrame(resizeMinimap);
}

function onMinimapPanelResizeEnd(event) {
  finishMinimapPanelResize(event.pointerId);
}

function finishMinimapPanelResize(pointerId) {
  const resize = state.minimapWindowResize;
  if (!resize || pointerId !== undefined && pointerId !== resize.pointerId) return;

  state.minimapWindowResize = null;
  if (resize.handle.hasPointerCapture(resize.pointerId)) {
    resize.handle.releasePointerCapture(resize.pointerId);
  }
}

function toggleLeftPanel() {
  state.leftCollapsed = !state.leftCollapsed;
  els.appShell.classList.toggle("is-left-collapsed", state.leftCollapsed);
  els.leftPanel.classList.toggle("is-collapsed", state.leftCollapsed);
  refreshPanelToggleLabels();
  requestAnimationFrame(() => {
    resizeCanvas();
    resizeMinimap();
  });
}

function toggleDetailPanel() {
  if (state.detailCollapsed) {
    expandDetailPanel();
  } else {
    collapseDetailPanel();
  }
}

function collapseDetailPanel() {
  if (!state.detailCollapsed) {
    state.previousDetailHeight = Math.max(state.detailHeight, 220);
  }
  state.detailCollapsed = true;
  els.graphStage.classList.add("is-detail-collapsed");
  els.detailToggle.textContent = "⌃";
  refreshPanelToggleLabels();
  requestAnimationFrame(resizeCanvas);
}

function expandDetailPanel() {
  state.detailCollapsed = false;
  els.graphStage.classList.remove("is-detail-collapsed");
  els.detailToggle.textContent = "⌄";
  refreshPanelToggleLabels();
  setDetailHeight(state.previousDetailHeight || 300);
  requestAnimationFrame(resizeCanvas);
}

function refreshPanelToggleLabels() {
  els.explorerToggle.title = state.explorerCollapsed ? t("expandPanel") : t("collapsePanel");
  els.minimapExpandButton.title = state.explorerExpanded ? t("restoreMinimap") : t("expandMinimap");
  els.minimapExpandButton.textContent = state.explorerExpanded ? "⤢" : "⛶";
  els.minimapExpandButton.setAttribute("aria-expanded", String(state.explorerExpanded));
  els.leftPanelToggle.title = state.leftCollapsed ? t("expandLeft") : t("collapseLeft");
  els.detailToggle.title = state.detailCollapsed ? t("expandDetail") : t("collapseDetail");
}

function openImageModal(figure) {
  if (!figure?.src) return;
  const targetId = figure.targetId || figure.figureId || figure.imagePath || "";
  const sourceFigure = findFigureByTargetId(targetId);
  els.imageModal.hidden = false;
  els.imageModalImg.src = figure.src;
  els.imageModalImg.alt = figure.description || figure.title || t("figureEvidence");
  els.imageModalTitle.textContent = figure.title || t("figureEvidence");
  els.imageModalDescription.textContent = figure.description || t("noFigureDescription");
  els.imageModalMeta.innerHTML = `
    ${figure.figureId ? `<div class="kv-row"><span>${escapeHtml(t("figureId"))}</span><strong>${escapeHtml(figure.figureId)}</strong></div>` : ""}
    ${targetId ? renderAnnotationForm("image", targetId, sourceFigure?.annotations || {}) : ""}
  `;
  if (targetId) bindAnnotationForm("image", targetId, els.imageModalMeta);
}

function closeImageModal() {
  els.imageModal.hidden = true;
  els.imageModalImg.removeAttribute("src");
}

function findFigureByTargetId(targetId) {
  if (!targetId) return null;
  for (const figure of allGraphFigures()) {
    if (figure.targetId === targetId || figure.figureId === targetId || figure.imagePath === targetId) {
      return figure;
    }
  }
  return null;
}

function allGraphFigures() {
  return [
    ...state.nodes.flatMap((node) => node.figures || []),
    ...state.edges.flatMap((edge) => edge.figures || []),
  ];
}

function tick() {
  if (state.alpha > 0.015) {
    stepPhysics();
  }
  draw();
  if (!state.explorerCollapsed) drawMinimap();
  requestAnimationFrame(tick);
}

function stepPhysics() {
  const nodes = state.nodes;
  const edges = state.edges;
  const alpha = state.alpha;

  for (const node of nodes) {
    node.vx *= 0.86;
    node.vy *= 0.86;
    node.vx += (typeBias(node.type) - node.x) * 0.0009 * alpha;
    node.vy += -node.y * 0.0007 * alpha;
  }

  for (let i = 0; i < nodes.length; i += 1) {
    for (let j = i + 1; j < nodes.length; j += 1) {
      const a = nodes[i];
      const b = nodes[j];
      const dx = b.x - a.x || 0.01;
      const dy = b.y - a.y || 0.01;
      const distanceSq = dx * dx + dy * dy;
      const distance = Math.sqrt(distanceSq);
      const minDistance = a.radius + b.radius + 30;
      const force = (distance < minDistance ? 0.85 : 0.32) * 2200 * alpha / Math.max(distanceSq, 80);
      const fx = (dx / distance) * force;
      const fy = (dy / distance) * force;
      a.vx -= fx;
      a.vy -= fy;
      b.vx += fx;
      b.vy += fy;
    }
  }

  for (const edge of edges) {
    const dx = edge.target.x - edge.source.x;
    const dy = edge.target.y - edge.source.y;
    const distance = Math.sqrt(dx * dx + dy * dy) || 1;
    const desired = edge.predicate === "requires" ? 118 : edge.predicate === "tests" ? 132 : 150;
    const strength = edge.predicate === "contains" ? 0.011 : 0.015;
    const force = (distance - desired) * strength * alpha;
    const fx = (dx / distance) * force;
    const fy = (dy / distance) * force;
    edge.source.vx += fx;
    edge.source.vy += fy;
    edge.target.vx -= fx;
    edge.target.vy -= fy;
  }

  for (const node of nodes) {
    if (node.fixed) {
      node.x = node.fixed.x;
      node.y = node.fixed.y;
      node.vx = 0;
      node.vy = 0;
    } else {
      node.x += clamp(node.vx, -8, 8);
      node.y += clamp(node.vy, -8, 8);
    }
  }

  state.alpha *= 0.988;
}

function draw() {
  const { width, height, dpr } = state.size;
  ctx.save();
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, width, height);

  const displayState = getGraphDisplayState();

  for (const edge of state.edges) {
    drawEdge(edge, displayState);
  }

  const activeNodeId = state.hovered?.kind === "node"
    ? state.hovered.id
    : state.selected?.kind === "node"
      ? state.selected.id
      : null;
  const selectedNodeIds = new Set(state.nodes.filter(isNodeSelected).map((node) => node.id));
  const orderedNodes = MinimapHelpers.orderNodesForRendering(
    state.nodes,
    activeNodeId,
    new Set(),
    selectedNodeIds,
  );
  for (const node of orderedNodes) {
    drawNode(node, displayState);
  }

  ctx.restore();
}

function getGraphDisplayState() {
  return {
    filteredEdgeIds: new Set(getFilteredTriples().map((triple) => triple.edgeId)),
    hasFilter: Boolean(state.search || state.focusNodeId || state.predicate !== "all"),
  };
}

function getEdgeVisual(edge, displayState, options = {}) {
  const includeSelection = options.includeSelection !== false;
  const active = includeSelection && isEdgeSelected(edge)
    || state.hovered?.kind === "edge" && state.hovered.id === edge.id;
  const related = displayState.filteredEdgeIds.has(edge.id);
  return {
    active,
    related,
    color: active ? "#d4472f" : predicateStyle[edge.predicate] || "#8d9890",
    opacity: !displayState.hasFilter || related || active ? 0.92 : 0.13,
  };
}

function getNodeVisual(node, displayState, options = {}) {
  const style = typeStyle[node.type] || typeStyle.Node;
  const includeSelection = options.includeSelection !== false;
  const active = includeSelection && isNodeSelected(node)
    || state.hovered?.kind === "node" && state.hovered.id === node.id;
  const related = !displayState.hasFilter || nodeIsInFilteredEdges(node, displayState.filteredEdgeIds);
  return {
    active,
    related,
    style,
    color: active ? "#d4472f" : style.color,
    fill: active ? "#fde7df" : style.fill,
    opacity: related || active ? 1 : 0.22,
  };
}

function drawEdge(edge, displayState) {
  const source = worldToScreen(edge.source.x, edge.source.y);
  const target = worldToScreen(edge.target.x, edge.target.y);
  const visual = getEdgeVisual(edge, displayState);
  const angle = Math.atan2(target.y - source.y, target.x - source.x);
  const sourceRadius = edge.source.radius * state.view.scale + 4;
  const targetRadius = edge.target.radius * state.view.scale + 7;
  const start = {
    x: source.x + Math.cos(angle) * sourceRadius,
    y: source.y + Math.sin(angle) * sourceRadius,
  };
  const end = {
    x: target.x - Math.cos(angle) * targetRadius,
    y: target.y - Math.sin(angle) * targetRadius,
  };

  ctx.save();
  ctx.globalAlpha = visual.opacity;
  ctx.strokeStyle = visual.color;
  ctx.lineWidth = visual.active ? 2.6 : 1.35;
  ctx.beginPath();
  ctx.moveTo(start.x, start.y);
  ctx.lineTo(end.x, end.y);
  ctx.stroke();

  const arrowSize = visual.active ? 9 : 7;
  ctx.fillStyle = visual.color;
  ctx.beginPath();
  ctx.moveTo(end.x, end.y);
  ctx.lineTo(end.x - Math.cos(angle - 0.45) * arrowSize, end.y - Math.sin(angle - 0.45) * arrowSize);
  ctx.lineTo(end.x - Math.cos(angle + 0.45) * arrowSize, end.y - Math.sin(angle + 0.45) * arrowSize);
  ctx.closePath();
  ctx.fill();

  if (visual.active || state.view.scale > 1.12) {
    drawEdgeLabel(edge, start, end, visual.color);
  }
  ctx.restore();
}

function drawEdgeLabel(edge, start, end, color) {
  const label = getPredicateLabel(edge.predicate);
  const x = (start.x + end.x) / 2;
  const y = (start.y + end.y) / 2;
  ctx.font = "12px Microsoft YaHei, Segoe UI, Arial";
  const metrics = ctx.measureText(label);
  const width = Math.min(metrics.width + 14, 96);
  ctx.fillStyle = "rgba(255,255,255,0.88)";
  roundedRect(ctx, x - width / 2, y - 12, width, 22, 6);
  ctx.fill();
  ctx.fillStyle = color;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(label, x, y);
}

function drawNode(node, displayState) {
  const point = worldToScreen(node.x, node.y);
  const visual = getNodeVisual(node, displayState);
  const style = visual.style;
  const radius = Math.max(7, node.radius * state.view.scale);

  ctx.save();
  ctx.globalAlpha = visual.opacity;
  ctx.lineWidth = visual.active ? 3 : 1.5;
  ctx.strokeStyle = visual.color;
  ctx.fillStyle = visual.fill;

  if (node.type === "ChapterSection") {
    const w = clamp(88 + node.title.length * 4, 104, 156) * Math.sqrt(state.view.scale);
    const h = 34 * Math.sqrt(state.view.scale);
    roundedRect(ctx, point.x - w / 2, point.y - h / 2, w, h, 8);
    ctx.fill();
    ctx.stroke();
    drawNodeText(node.title, point.x, point.y, w - 14, style.color, true);
  } else if (node.type === "Problem") {
    drawDiamond(point.x, point.y, radius + 5);
    ctx.fill();
    ctx.stroke();
    drawNodeLabel(node.title, point.x, point.y + radius + 14, style.color, visual.active);
  } else {
    ctx.beginPath();
    ctx.arc(point.x, point.y, radius, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
    const inner = Math.max(3, Math.min(radius * 0.36, 6));
    ctx.beginPath();
    ctx.arc(point.x, point.y, inner, 0, Math.PI * 2);
    ctx.fillStyle = style.color;
    ctx.fill();
    drawNodeLabel(node.title, point.x, point.y + radius + 13, style.color, visual.active);
  }

  if (visual.active) {
    ctx.beginPath();
    ctx.arc(point.x, point.y, radius + 10, 0, Math.PI * 2);
    ctx.strokeStyle = "rgba(212, 71, 47, 0.24)";
    ctx.lineWidth = 7;
    ctx.stroke();
  }

  ctx.restore();
}

function drawNodeLabel(text, x, y, color, active) {
  const maxWidth = active ? 132 : 92;
  const label = fitText(text, maxWidth);
  ctx.font = `${active ? "700 " : ""}12px Microsoft YaHei, Segoe UI, Arial`;
  const width = Math.min(ctx.measureText(label).width + 12, maxWidth + 12);
  ctx.fillStyle = "rgba(255,255,255,0.82)";
  roundedRect(ctx, x - width / 2, y - 10, width, 20, 6);
  ctx.fill();
  ctx.fillStyle = color;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(label, x, y);
}

function drawNodeText(text, x, y, maxWidth, color, active) {
  ctx.font = `${active ? "700 " : ""}12px Microsoft YaHei, Segoe UI, Arial`;
  ctx.fillStyle = color;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(fitText(text, maxWidth), x, y);
}

function onWheel(event) {
  event.preventDefault();
  const delta = event.deltaY < 0 ? 1.12 : 0.9;
  const rect = els.canvas.getBoundingClientRect();
  const mouse = { x: event.clientX - rect.left, y: event.clientY - rect.top };
  const before = screenToWorld(mouse.x, mouse.y);
  state.view.scale = clamp(state.view.scale * delta, 0.28, 3.2);
  const after = worldToScreen(before.x, before.y);
  state.view.x += mouse.x - after.x;
  state.view.y += mouse.y - after.y;
  drawMinimap();
}

function onDetailResizeStart(event) {
  event.preventDefault();
  els.detailResizer.setPointerCapture(event.pointerId);
  const stageRect = els.graphStage.getBoundingClientRect();
  state.detailResize = {
    pointerId: event.pointerId,
    startY: event.clientY,
    startHeight: state.detailHeight,
    min: 220,
    max: Math.max(240, Math.min(560, stageRect.height - 220)),
  };
  els.detailResizer.classList.add("is-dragging");
  window.addEventListener("pointermove", onDetailResizeMove);
  window.addEventListener("pointerup", onDetailResizeEnd);
}

function onDetailResizeMove(event) {
  if (!state.detailResize || event.pointerId !== state.detailResize.pointerId) return;
  const next = state.detailResize.startHeight - (event.clientY - state.detailResize.startY);
  if (next <= state.detailResize.min) {
    collapseDetailPanel();
    endDetailResize();
    return;
  }
  setDetailHeight(clamp(next, state.detailResize.min, state.detailResize.max));
}

function onDetailResizeEnd(event) {
  if (state.detailResize && event.pointerId !== state.detailResize.pointerId) return;
  endDetailResize();
}

function endDetailResize() {
  state.detailResize = null;
  els.detailResizer.classList.remove("is-dragging");
  window.removeEventListener("pointermove", onDetailResizeMove);
  window.removeEventListener("pointerup", onDetailResizeEnd);
}

function setDetailHeight(height) {
  if (state.detailCollapsed) return;
  state.detailHeight = Math.round(height);
  els.graphStage.style.setProperty("--detail-height", `${state.detailHeight}px`);
  resizeCanvas();
}

function onPointerDown(event) {
  els.canvas.setPointerCapture(event.pointerId);
  const point = getPointer(event);
  const node = hitTestNode(point.x, point.y);
  const edge = node ? null : hitTestEdge(point.x, point.y);
  state.pointer = point;
  state.pointerPrevious = point;

  if (node) {
    state.drag = { mode: "node", node, start: point, moved: false };
    node.fixed = screenToWorld(point.x, point.y);
    state.alpha = Math.max(state.alpha, 0.28);
  } else {
    state.drag = { mode: "pan", edge, start: point, moved: false };
  }
  els.canvas.classList.add("dragging");
}

function onPointerMove(event) {
  const point = getPointer(event);
  state.pointer = point;

  if (state.drag?.mode === "node") {
    const world = screenToWorld(point.x, point.y);
    state.drag.node.fixed = world;
    state.drag.node.x = world.x;
    state.drag.node.y = world.y;
    state.drag.moved = distance(point, state.drag.start) > 4;
    hideHover();
    drawMinimap();
    return;
  }

  if (state.drag?.mode === "pan") {
    const dx = point.x - state.pointerPrevious.x;
    const dy = point.y - state.pointerPrevious.y;
    state.view.x += dx;
    state.view.y += dy;
    state.drag.moved = state.drag.moved || distance(point, state.drag.start) > 4;
    hideHover();
    drawMinimap();
  } else {
    updateHover(point);
  }

  state.pointerPrevious = point;
}

function onPointerUp(event) {
  const point = getPointer(event);
  const drag = state.drag;
  els.canvas.classList.remove("dragging");

  if (drag?.mode === "node") {
    drag.node.fixed = null;
    if (!drag.moved) selectNode(drag.node);
  } else if (drag?.mode === "pan" && !drag.moved) {
    const node = hitTestNode(point.x, point.y);
    const edge = node ? null : hitTestEdge(point.x, point.y);
    if (node) selectNode(node);
    else if (edge) selectEdge(edge);
    else {
      state.selected = null;
      state.focusNodeId = null;
      renderTripleList();
      drawMinimap();
      renderDetail();
    }
  }

  state.drag = null;
  state.pointerPrevious = null;
}

function onPointerLeave() {
  if (!state.drag) {
    hideHover();
  }
}

function getPointer(event) {
  const rect = els.canvas.getBoundingClientRect();
  const point = { x: event.clientX - rect.left, y: event.clientY - rect.top };
  if (!state.pointerPrevious) state.pointerPrevious = point;
  return point;
}

function updateHover(point) {
  const node = hitTestNode(point.x, point.y);
  const edge = node ? null : hitTestEdge(point.x, point.y);

  if (node) {
    state.hovered = { kind: "node", id: node.id };
    showHover(renderNodePreview(node), point);
    drawMinimap();
  } else if (edge) {
    state.hovered = { kind: "edge", id: edge.id };
    showHover(renderEdgePreview(edge), point);
    drawMinimap();
  } else {
    hideHover();
  }
}

function renderNodePreview(node) {
  const firstFigure = node.figures[0];
  const quote = displayText(firstText(node.evidence));
  return `
    <h3 class="preview-title">${escapeHtml(node.title)}</h3>
    <p class="preview-subtitle">${escapeHtml(getTypeLabel(node.type))} · ${node.degree} ${escapeHtml(t("relationsUnit"))}</p>
    ${quote ? `<p class="preview-text">${escapeHtml(truncate(quote, 120))}</p>` : ""}
    ${firstFigure ? `<img class="preview-image" src="${escapeHtml(firstFigure.src)}" alt="${escapeHtml(firstFigure.description || node.title)}" />` : ""}
  `;
}

function renderEdgePreview(edge) {
  const firstFigure = edge.figures[0];
  const quote = displayText(firstText(edge.evidence));
  return `
    <h3 class="preview-title">${escapeHtml(edge.source.title)} → ${escapeHtml(edge.target.title)}</h3>
    <p class="preview-subtitle">${escapeHtml(getPredicateLabel(edge.predicate))}</p>
    ${quote ? `<p class="preview-text">${escapeHtml(truncate(quote, 140))}</p>` : ""}
    ${firstFigure ? `<img class="preview-image" src="${escapeHtml(firstFigure.src)}" alt="${escapeHtml(firstFigure.description || getPredicateLabel(edge.predicate))}" />` : ""}
  `;
}

function showHover(html, point) {
  els.hoverCard.hidden = false;
  els.hoverCard.innerHTML = html;
  const wrapRect = els.canvasWrap.getBoundingClientRect();
  const cardRect = els.hoverCard.getBoundingClientRect();
  let x = point.x + 16;
  let y = point.y + 16;
  if (x + cardRect.width > wrapRect.width - 8) x = point.x - cardRect.width - 16;
  if (y + cardRect.height > wrapRect.height - 8) y = point.y - cardRect.height - 16;
  els.hoverCard.style.left = `${clamp(x, 8, wrapRect.width - cardRect.width - 8)}px`;
  els.hoverCard.style.top = `${clamp(y, 8, wrapRect.height - cardRect.height - 8)}px`;
}

function hideHover() {
  state.hovered = null;
  els.hoverCard.hidden = true;
  drawMinimap();
}

function hitTestNode(x, y) {
  for (let i = state.nodes.length - 1; i >= 0; i -= 1) {
    const node = state.nodes[i];
    const point = worldToScreen(node.x, node.y);
    const radius = node.type === "ChapterSection" ? 34 * Math.sqrt(state.view.scale) : node.radius * state.view.scale + 9;
    if (distance({ x, y }, point) <= radius) return node;
  }
  return null;
}

function hitTestEdge(x, y) {
  let best = null;
  let bestDistance = 9;
  for (const edge of state.edges) {
    const source = worldToScreen(edge.source.x, edge.source.y);
    const target = worldToScreen(edge.target.x, edge.target.y);
    const current = pointToSegmentDistance({ x, y }, source, target);
    if (current < bestDistance) {
      bestDistance = current;
      best = edge;
    }
  }
  return best;
}

function resizeCanvas() {
  const rect = els.canvasWrap.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  state.size.width = Math.max(320, rect.width);
  state.size.height = Math.max(280, rect.height);
  state.size.dpr = dpr;
  els.canvas.width = Math.floor(state.size.width * dpr);
  els.canvas.height = Math.floor(state.size.height * dpr);
  els.canvas.style.width = `${state.size.width}px`;
  els.canvas.style.height = `${state.size.height}px`;
  draw();
  drawMinimap();
}

function resizeMinimap() {
  const rect = els.minimapCanvas.getBoundingClientRect();
  if (!rect.width || !rect.height) return;
  const dpr = window.devicePixelRatio || 1;
  els.minimapCanvas.width = Math.floor(rect.width * dpr);
  els.minimapCanvas.height = Math.floor(rect.height * dpr);
  drawMinimap();
}

function zoomAtCenter(factor) {
  state.view.scale = clamp(state.view.scale * factor, 0.28, 3.2);
  drawMinimap();
}

function rotateGraph(delta) {
  state.view.rotation += delta;
  drawMinimap();
}

function resetView() {
  state.view = { x: 0, y: 0, scale: 1, rotation: 0 };
  state.selected = null;
  state.focusNodeId = null;
  state.alpha = Math.max(state.alpha, 0.35);
  renderTripleList();
  drawMinimap();
  renderDetail();
  drawMinimap();
}

function centerOnNodes(nodes) {
  if (!nodes.length) return;
  const cx = nodes.reduce((sum, node) => sum + node.x, 0) / nodes.length;
  const cy = nodes.reduce((sum, node) => sum + node.y, 0) / nodes.length;
  const projected = worldToScreen(cx, cy);
  state.view.x += state.size.width / 2 - projected.x;
  state.view.y += state.size.height / 2 - projected.y;
  drawMinimap();
}

function drawMinimap() {
  if (!els.minimapCanvas || state.explorerCollapsed) return;
  const dpr = window.devicePixelRatio || 1;
  const width = els.minimapCanvas.width / dpr;
  const height = els.minimapCanvas.height / dpr;
  if (!width || !height || !state.nodes.length) return;

  const displayState = getGraphDisplayState();
  const matchedNodeIds = getMinimapMatchedNodeIds();
  const selectedNodeId = state.selected?.kind === "node" ? state.selected.id : null;
  const activeNodeId = state.minimapHoveredNodeId ?? selectedNodeId;
  const includePersistentSelection = state.minimapHoveredNodeId == null;
  const oneHopContext = MinimapHelpers.buildOneHopContext(activeNodeId, state.edges);
  const ordinaryEmphasisNodeIds = new Set(matchedNodeIds);
  for (const node of state.nodes) {
    if (includePersistentSelection && isNodeSelected(node)) ordinaryEmphasisNodeIds.add(node.id);
  }
  const emphasis = Boolean(activeNodeId || ordinaryEmphasisNodeIds.size);
  const pulse = getMinimapPulse();
  const bounds = getGraphBounds();
  const pad = 18;
  const scale = Math.min((width - pad * 2) / bounds.width, (height - pad * 2) / bounds.height);
  const offsetX = (width - bounds.width * scale) / 2 - bounds.minX * scale;
  const offsetY = (height - bounds.height * scale) / 2 - bounds.minY * scale;

  minimapCtx.save();
  minimapCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
  minimapCtx.clearRect(0, 0, width, height);
  minimapCtx.fillStyle = "#f7f8f5";
  minimapCtx.fillRect(0, 0, width, height);

  const visibleEdges = state.edges.filter(
    (edge) => oneHopContext.edgeIds.has(edge.id) || minimapEdgeIsVisible(edge, displayState, matchedNodeIds),
  );
  const orderedEdges = [
    ...visibleEdges.filter((edge) => !oneHopContext.edgeIds.has(edge.id)),
    ...visibleEdges.filter((edge) => oneHopContext.edgeIds.has(edge.id)),
  ];
  for (const edge of orderedEdges) {
    const visual = getEdgeVisual(edge, displayState, { includeSelection: includePersistentSelection });
    const incident = oneHopContext.edgeIds.has(edge.id);
    const emphasized = visual.active || incident;
    minimapCtx.strokeStyle = visual.color;
    minimapCtx.globalAlpha = emphasized ? 0.96 : emphasis ? 0.14 : clamp(visual.opacity * 0.55, 0.08, 0.5);
    minimapCtx.lineWidth = incident ? 2.4 : emphasized ? 2.2 : 0.8;
    minimapCtx.beginPath();
    minimapCtx.moveTo(edge.source.x * scale + offsetX, edge.source.y * scale + offsetY);
    minimapCtx.lineTo(edge.target.x * scale + offsetX, edge.target.y * scale + offsetY);
    minimapCtx.stroke();
  }

  const visibleNodes = state.nodes.filter(
    (node) => oneHopContext.nodeIds.has(node.id) || minimapNodeIsVisible(node, displayState, matchedNodeIds),
  );
  const orderedNodes = MinimapHelpers.orderNodesForRendering(
    visibleNodes,
    activeNodeId,
    oneHopContext.nodeIds,
    ordinaryEmphasisNodeIds,
  );
  for (const node of orderedNodes) {
    const visual = getNodeVisual(node, displayState, { includeSelection: includePersistentSelection });
    const active = activeNodeId === node.id;
    const oneHopNeighbor = oneHopContext.nodeIds.has(node.id) && !active;
    const matched = matchedNodeIds.has(node.id);
    const ordinaryEmphasis = visual.active || matched;
    const emphasized = active || oneHopNeighbor || ordinaryEmphasis;
    const radius = active
      ? 6.4 + (matched ? pulse : 0)
      : oneHopNeighbor
        ? 5.2
        : ordinaryEmphasis
          ? 4.8 + (matched ? pulse : 0)
          : 2.9;
    minimapCtx.globalAlpha = emphasized ? 1 : emphasis ? 0.16 : clamp(visual.opacity * 0.78, 0.14, 0.78);
    minimapCtx.fillStyle = visual.color;
    minimapCtx.beginPath();
    minimapCtx.arc(node.x * scale + offsetX, node.y * scale + offsetY, radius, 0, Math.PI * 2);
    minimapCtx.fill();

    if (emphasized) {
      minimapCtx.globalAlpha = active ? 0.48 : oneHopNeighbor ? 0.36 : 0.32;
      minimapCtx.strokeStyle = active || ordinaryEmphasis ? "#d4472f" : visual.color;
      minimapCtx.lineWidth = active ? 4 : oneHopNeighbor ? 3 : 2.5;
      minimapCtx.beginPath();
      minimapCtx.arc(
        node.x * scale + offsetX,
        node.y * scale + offsetY,
        radius + (active ? 4.2 : 3.2),
        0,
        Math.PI * 2,
      );
      minimapCtx.stroke();
    }
  }

  drawMinimapNodeLabels({
    activeNodeId,
    oneHopContext,
    width,
    height,
    scale,
    offsetX,
    offsetY,
    displayState,
    includePersistentSelection,
  });

  minimapCtx.restore();
}

function drawMinimapNodeLabels({
  activeNodeId,
  oneHopContext,
  width,
  height,
  scale,
  offsetX,
  offsetY,
  displayState,
  includePersistentSelection,
}) {
  if (activeNodeId === null || activeNodeId === undefined) return;

  const compact = !state.explorerExpanded;
  const maxWidth = MinimapHelpers.getMinimapLabelMaxWidth(state.explorerExpanded);
  const paddingX = compact ? 6 : 8;
  const paddingY = compact ? 5 : 6;
  const titleFont = `${compact ? 600 : 700} ${compact ? 10 : 12}px Microsoft YaHei, Segoe UI, Arial`;
  const typeFont = `500 ${compact ? 9 : 10}px Microsoft YaHei, Segoe UI, Arial`;
  const titleLineHeight = compact ? 12 : 15;
  const typeLineHeight = compact ? 11 : 13;
  const textWidthLimit = maxWidth - paddingX * 2;
  const measureWithFont = (font, text) => {
    minimapCtx.font = font;
    return minimapCtx.measureText(text).width;
  };

  const contextNodes = state.nodes.filter((node) => oneHopContext.nodeIds.has(node.id));
  const ordered = MinimapHelpers.orderContextLabels(contextNodes, activeNodeId);
  const labels = ordered.map((node) => {
    const active = node.id === activeNodeId;
    const title = MinimapHelpers.truncateLabelText(
      node.title,
      textWidthLimit,
      (text) => measureWithFont(titleFont, text),
    );
    const type = MinimapHelpers.truncateLabelText(
      getTypeLabel(node.type),
      textWidthLimit,
      (text) => measureWithFont(typeFont, text),
    );
    const contentWidth = Math.max(
      measureWithFont(titleFont, title),
      measureWithFont(typeFont, type),
    );

    return {
      id: node.id,
      node,
      active,
      title,
      type,
      x: node.x * scale + offsetX,
      y: node.y * scale + offsetY,
      radius: active ? 11 : 8.5,
      width: Math.min(maxWidth, Math.ceil(contentWidth + paddingX * 2)),
      height: paddingY * 2 + titleLineHeight + typeLineHeight,
    };
  });
  const placed = MinimapHelpers.placeMinimapLabels(labels, {
    width,
    height,
    gap: compact ? 5 : 7,
    margin: 5,
  });

  for (const label of placed) {
    const visual = getNodeVisual(
      label.node,
      displayState,
      { includeSelection: includePersistentSelection },
    );
    const anchorX = clamp(label.x, label.left, label.left + label.width);
    const anchorY = clamp(label.y, label.top, label.top + label.height);

    minimapCtx.globalAlpha = label.active ? 0.92 : 0.58;
    minimapCtx.strokeStyle = label.active ? "#d4472f" : visual.color;
    minimapCtx.lineWidth = label.active ? 1.5 : 1;
    minimapCtx.beginPath();
    minimapCtx.moveTo(label.x, label.y);
    minimapCtx.lineTo(anchorX, anchorY);
    minimapCtx.stroke();

    minimapCtx.globalAlpha = 0.97;
    minimapCtx.fillStyle = "#ffffff";
    minimapCtx.strokeStyle = label.active ? "#d4472f" : "rgba(57, 72, 64, 0.5)";
    minimapCtx.lineWidth = label.active ? 2 : 1;
    roundedRect(minimapCtx, label.left, label.top, label.width, label.height, compact ? 5 : 6);
    minimapCtx.fill();
    minimapCtx.stroke();

    minimapCtx.globalAlpha = 1;
    minimapCtx.textAlign = "left";
    minimapCtx.textBaseline = "top";
    minimapCtx.fillStyle = "#17211c";
    minimapCtx.font = titleFont;
    minimapCtx.fillText(label.title, label.left + paddingX, label.top + paddingY);
    minimapCtx.fillStyle = label.active ? "#b83a27" : "#647068";
    minimapCtx.font = typeFont;
    minimapCtx.fillText(
      label.type,
      label.left + paddingX,
      label.top + paddingY + titleLineHeight,
    );
  }
}

function onMinimapPointerDown(event) {
  const mapping = getMinimapMapping();
  if (!mapping) return;
  els.minimapCanvas.setPointerCapture(event.pointerId);
  const point = getMinimapPointer(event);
  const node = hitTestMinimapNode(point, mapping);
  state.minimapDrag = {
    pointerId: event.pointerId,
    mode: node ? "node" : "pan",
    node,
    startPoint: point,
    startCenter: screenToWorld(state.size.width / 2, state.size.height / 2),
    moved: false,
    mapping,
  };
  els.minimapCanvas.classList.add("dragging");
  els.minimapCanvas.style.cursor = node ? "pointer" : "grabbing";
}

function onMinimapPointerMove(event) {
  const point = getMinimapPointer(event);
  const mapping = getMinimapMapping();
  if (!mapping) return;

  if (state.minimapDrag) {
    const drag = state.minimapDrag;
    drag.moved = drag.moved || distance(point, drag.startPoint) > 4;
    if (drag.mode === "pan") {
      const dx = (point.x - drag.startPoint.x) / drag.mapping.scale;
      const dy = (point.y - drag.startPoint.y) / drag.mapping.scale;
      centerViewOnWorld({ x: drag.startCenter.x + dx, y: drag.startCenter.y + dy });
      drawMinimap();
    }
    return;
  }

  const node = hitTestMinimapNode(point, mapping);
  if (node) {
    state.minimapHoveredNodeId = node.id;
    els.minimapCanvas.style.cursor = "pointer";
  } else {
    state.minimapHoveredNodeId = null;
    els.minimapCanvas.style.cursor = "grab";
  }
  drawMinimap();
}

function onMinimapPointerUp(event) {
  const drag = state.minimapDrag;
  els.minimapCanvas.classList.remove("dragging");
  els.minimapCanvas.style.cursor = "grab";
  if (drag && event.pointerId === drag.pointerId && !drag.moved) {
    if (drag.mode === "node" && drag.node) {
      focusMinimapNode(drag.node);
    } else {
      const mapping = getMinimapMapping();
      if (mapping) centerViewOnWorld(minimapPointToWorld(getMinimapPointer(event), mapping));
    }
  }
  state.minimapDrag = null;
  drawMinimap();
}

function onMinimapPointerCancel(event) {
  if (!state.minimapDrag || event.pointerId !== state.minimapDrag.pointerId) return;
  state.minimapDrag = null;
  els.minimapCanvas.classList.remove("dragging");
  els.minimapCanvas.style.cursor = "grab";
  drawMinimap();
}

function onMinimapPointerLeave() {
  if (state.minimapDrag) return;
  state.minimapHoveredNodeId = null;
  els.minimapCanvas.style.cursor = "grab";
  drawMinimap();
}

function focusMinimapNode(node) {
  state.selected = { kind: "node", id: node.id };
  state.focusNodeId = node.id;
  state.view.scale = 1.65;
  centerViewOnWorld(node);
  renderTripleList();
  renderDetail();
  pulseMinimapMatches();
  drawMinimap();
}

function centerViewOnWorld(world) {
  const projected = worldToScreen(world.x, world.y);
  state.view.x += state.size.width / 2 - projected.x;
  state.view.y += state.size.height / 2 - projected.y;
}

function getMinimapPointer(event) {
  const rect = els.minimapCanvas.getBoundingClientRect();
  return { x: event.clientX - rect.left, y: event.clientY - rect.top };
}

function minimapPointToWorld(point, mapping) {
  return {
    x: (point.x - mapping.offsetX) / mapping.scale,
    y: (point.y - mapping.offsetY) / mapping.scale,
  };
}

function hitTestMinimapNode(point, mapping) {
  const displayState = getGraphDisplayState();
  const matchedNodeIds = getMinimapMatchedNodeIds();
  let best = null;
  let bestDistance = 10;
  for (const node of state.nodes) {
    if (!minimapNodeIsVisible(node, displayState, matchedNodeIds)) continue;
    const nodePoint = {
      x: node.x * mapping.scale + mapping.offsetX,
      y: node.y * mapping.scale + mapping.offsetY,
    };
    const current = distance(point, nodePoint);
    if (current < bestDistance) {
      bestDistance = current;
      best = node;
    }
  }
  return best;
}

function getMinimapMatchedNodeIds() {
  const query = (state.minimapSearch || state.search || "").trim().toLowerCase();
  if (!query) return new Set();
  return new Set(state.nodes.filter((node) => searchableNodeText(node).includes(query)).map((node) => node.id));
}

function pulseMinimapMatches() {
  state.minimapPulseUntil = performance.now() + 2600;
}

function getMinimapPulse() {
  if (performance.now() > state.minimapPulseUntil) return 0;
  return 1.6 + Math.sin(performance.now() / 130) * 1.2;
}

function minimapEdgeIsVisible(edge, displayState, matchedNodeIds) {
  if (!displayState.hasFilter) return true;
  return displayState.filteredEdgeIds.has(edge.id) || isEdgeSelected(edge) || matchedNodeIds.has(edge.source.id) || matchedNodeIds.has(edge.target.id);
}

function minimapNodeIsVisible(node, displayState, matchedNodeIds) {
  if (!displayState.hasFilter) return true;
  return nodeIsInFilteredEdges(node, displayState.filteredEdgeIds) || isNodeSelected(node) || matchedNodeIds.has(node.id);
}

function getMinimapMapping() {
  const rect = els.minimapCanvas.getBoundingClientRect();
  if (!rect.width || !rect.height || !state.nodes.length) return null;
  const bounds = getGraphBounds();
  const pad = 18;
  const scale = Math.min((rect.width - pad * 2) / bounds.width, (rect.height - pad * 2) / bounds.height);
  return {
    scale,
    offsetX: (rect.width - bounds.width * scale) / 2 - bounds.minX * scale,
    offsetY: (rect.height - bounds.height * scale) / 2 - bounds.minY * scale,
  };
}

function getGraphBounds() {
  const xs = state.nodes.map((node) => node.x);
  const ys = state.nodes.map((node) => node.y);
  const minX = Math.min(...xs) - 60;
  const maxX = Math.max(...xs) + 60;
  const minY = Math.min(...ys) - 60;
  const maxY = Math.max(...ys) + 60;
  return {
    minX,
    minY,
    width: Math.max(1, maxX - minX),
    height: Math.max(1, maxY - minY),
  };
}

function worldToScreen(x, y) {
  const c = Math.cos(state.view.rotation);
  const s = Math.sin(state.view.rotation);
  const rx = x * c - y * s;
  const ry = x * s + y * c;
  return {
    x: state.size.width / 2 + state.view.x + rx * state.view.scale,
    y: state.size.height / 2 + state.view.y + ry * state.view.scale,
  };
}

function screenToWorld(x, y) {
  const tx = (x - state.size.width / 2 - state.view.x) / state.view.scale;
  const ty = (y - state.size.height / 2 - state.view.y) / state.view.scale;
  const c = Math.cos(-state.view.rotation);
  const s = Math.sin(-state.view.rotation);
  return {
    x: tx * c - ty * s,
    y: tx * s + ty * c,
  };
}

function isNodeSelected(node) {
  if (state.selected?.kind === "node" && state.selected.id === node.id) return true;
  if (state.selected?.kind === "triple") {
    const triple = state.triples.find((item) => item.id === state.selected.id);
    return triple?.subject?.id === node.id || triple?.object?.id === node.id;
  }
  if (state.selected?.kind === "edge") {
    const edge = state.edgeById.get(state.selected.id);
    return edge?.source.id === node.id || edge?.target.id === node.id;
  }
  return false;
}

function isEdgeSelected(edge) {
  if (state.selected?.kind === "edge" && state.selected.id === edge.id) return true;
  if (state.selected?.kind === "triple") {
    const triple = state.triples.find((item) => item.id === state.selected.id);
    return triple?.edgeId === edge.id;
  }
  if (state.selected?.kind === "node") {
    return edge.source.id === state.selected.id || edge.target.id === state.selected.id;
  }
  return false;
}

function nodeIsInFilteredEdges(node, filteredEdgeIds) {
  for (const edge of state.edges) {
    if (filteredEdgeIds.has(edge.id) && (edge.source.id === node.id || edge.target.id === node.id)) {
      return true;
    }
  }
  return false;
}

function getNodeTitle(raw) {
  const props = raw.properties || {};
  for (const key of nodeTitleKeys) {
    const value = displayText(firstDisplayText(props[key]));
    if (isUsableTitle(value)) return value;
  }
  for (const [key, value] of Object.entries(props)) {
    if (!/(^|_)(title|name|text|question|label)$/i.test(key)) continue;
    const candidate = displayText(firstDisplayText(value));
    if (isUsableTitle(candidate)) return candidate;
  }
  return `${getTypeLabel(raw.label || "Node")} ${String(raw.node_id || "").slice(-4) || ""}`.trim();
}

function sanitizeFields(source, blocked) {
  const cleaned = {};
  for (const [key, value] of Object.entries(source || {})) {
    if (blocked.has(key)) continue;
    if (key === "figures") continue;
    if (!hasValue(value)) continue;
    cleaned[key] = value;
  }
  return cleaned;
}

function extractQuotes(evidence) {
  if (!Array.isArray(evidence)) return [];
  return evidence
    .map((item) => displayText(item?.quote_or_summary))
    .filter(Boolean);
}

function normalizeFigures(figures) {
  if (!Array.isArray(figures)) return [];
  const seen = new Set();
  return figures
    .map((figure) => {
      const src = normalizeImagePath(figure?.image_path);
      if (!src || seen.has(src)) return null;
      seen.add(src);
      const imagePath = figure?.image_path || "";
      return {
        src,
        name: displayText(figure.name),
        description: displayText(figure.description),
        imagePath,
        figureId: figure.figure_id || "",
        targetId: figure.figure_id || imagePath,
        annotations: normalizeAnnotation(figure.web_annotations),
      };
    })
    .filter(Boolean);
}

function normalizeAnnotation(annotation) {
  if (!annotation || typeof annotation !== "object") {
    return { tags: [], note: "" };
  }
  const tags = Array.isArray(annotation.tags)
    ? annotation.tags.map((tag) => String(tag).trim()).filter(Boolean)
    : [];
  return {
    tags: [...new Set(tags)],
    note: String(annotation.note || "").trim(),
  };
}

function normalizeAnnotationTemplate(template) {
  if (!template || typeof template !== "object") return null;
  return {
    id: Number(template.id),
    targetKind: String(template.target_kind || ""),
    name: String(template.name || "未命名模板"),
    tags: Array.isArray(template.tags) ? template.tags.map((tag) => String(tag).trim()).filter(Boolean) : [],
    note: String(template.note || "").trim(),
  };
}

function normalizeImagePath(path) {
  if (!path || typeof path !== "string") return "";
  if (/^(https?:|data:|blob:)/i.test(path)) return path;
  if (API_CONFIG.enabled) return getImageUrl(path);
  const normalized = path.replaceAll("\\", "/");
  const imageIndex = normalized.lastIndexOf("images/");
  const suffix = imageIndex >= 0 ? normalized.slice(imageIndex) : `images/${normalized.split("/").pop()}`;
  return `${IMAGE_DATA_DIR}/${suffix}`;
}

function mergeFigures(...groups) {
  const seen = new Set();
  const merged = [];
  for (const group of groups) {
    for (const figure of group || []) {
      if (!figure?.src || seen.has(figure.src)) continue;
      seen.add(figure.src);
      merged.push(figure);
    }
  }
  return merged;
}

function searchableText(triple) {
  return [
    triple.subject?.title,
    triple.object?.title,
    triple.predicate,
    getPredicateLabel(triple.predicate),
    triple.id,
    triple.edgeId,
    ...triple.evidence,
    ...(triple.edge?.evidence || []),
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
}

function searchableNodeText(node) {
  return [
    node.title,
    node.id,
    node.type,
    getTypeLabel(node.type),
    ...Object.entries(node.props || {}).map(([key, value]) => formatFieldValue(key, value)),
    ...node.evidence,
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
}

function searchableEdgeText(edge) {
  return [
    edge.id,
    edge.predicate,
    getPredicateLabel(edge.predicate),
    edge.source.title,
    edge.target.title,
    ...Object.entries(edge.props || {}).map(([key, value]) => formatFieldValue(key, value)),
    ...edge.evidence,
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
}

function showLoadError(error) {
  els.tripleList.innerHTML = `<div class="empty-state">${escapeHtml(t("readFailed"))}: ${escapeHtml(error.message)}</div>`;
  els.detailPanel.innerHTML = `<p>${escapeHtml(t("openHttpHint"))}</p>`;
}

function typeBias(type) {
  if (type === "ChapterSection") return -260;
  if (type === "Problem") return 290;
  return 60;
}

function roundedRect(context, x, y, width, height, radius) {
  const r = Math.min(radius, width / 2, height / 2);
  context.beginPath();
  context.moveTo(x + r, y);
  context.lineTo(x + width - r, y);
  context.quadraticCurveTo(x + width, y, x + width, y + r);
  context.lineTo(x + width, y + height - r);
  context.quadraticCurveTo(x + width, y + height, x + width - r, y + height);
  context.lineTo(x + r, y + height);
  context.quadraticCurveTo(x, y + height, x, y + height - r);
  context.lineTo(x, y + r);
  context.quadraticCurveTo(x, y, x + r, y);
  context.closePath();
}

function drawDiamond(x, y, radius) {
  ctx.beginPath();
  ctx.moveTo(x, y - radius);
  ctx.lineTo(x + radius, y);
  ctx.lineTo(x, y + radius);
  ctx.lineTo(x - radius, y);
  ctx.closePath();
}

function fitText(text, maxWidth) {
  const value = String(text || "");
  if (ctx.measureText(value).width <= maxWidth) return value;
  let result = value;
  while (result.length > 1 && ctx.measureText(`${result}…`).width > maxWidth) {
    result = result.slice(0, -1);
  }
  return `${result}…`;
}

function truncate(text, length) {
  const value = String(text || "");
  return value.length > length ? `${value.slice(0, length - 1)}…` : value;
}

function firstText(values) {
  return (values || []).find(Boolean) || "";
}

function firstDisplayText(value) {
  if (Array.isArray(value)) {
    for (const item of value) {
      const text = firstDisplayText(item);
      if (text) return text;
    }
    return "";
  }
  if (value && typeof value === "object") {
    return firstDisplayText(value.title || value.name || value.text || value.description || value.quote_or_summary);
  }
  return String(value || "").trim();
}

function isUsableTitle(value) {
  if (!value) return false;
  if (/^canon_[a-z0-9_]+$/i.test(value)) return false;
  if (/^[a-z]+_[a-z0-9_]+_[a-f0-9]{8,}$/i.test(value)) return false;
  return true;
}

function localizeDisplayValue(value) {
  if (!hasValue(value)) return "";
  const text = formatValue(value);
  return text
    .split(/\s*,\s*/)
    .map(localizeKnownTextPart)
    .join("，");
}

function localizeKnownTextPart(value) {
  let text = String(value || "").trim();
  if (!text) return "";
  text = displayValueLabels[text] || text;
  if (state.language !== "zh") return text;
  Object.entries(I18N.zh.predicateLabels || {}).forEach(([key, label]) => {
    text = text.replaceAll(key, label);
  });
  Object.entries(I18N.zh.typeLabels || {}).forEach(([key, label]) => {
    text = text.replaceAll(key, label);
  });
  Object.entries(displayValueLabels).forEach(([key, label]) => {
    text = text.replaceAll(key, label);
  });
  return text;
}

function displayText(value) {
  const text = localizeDisplayValue(value).trim();
  if (!text) return "";
  if (hasChinese(text)) return text;
  if (looksLikeEnglishSentence(text)) return "";
  return text;
}

function formatFieldValue(key, value) {
  if (Array.isArray(value)) {
    return value.map((item) => formatFieldValue(key, item)).filter(Boolean).join("、");
  }
  if (value && typeof value === "object") {
    return formatObjectValue(value);
  }
  return displayText(value);
}

function formatObjectValue(value) {
  const entries = Object.entries(value || {})
    .filter(([, item]) => hasValue(item))
    .map(([key, item]) => [key, formatFieldValue(key, item)])
    .filter(([, item]) => hasValue(item))
    .map(([key, item]) => `${getFieldName(key)}：${item}`);
  return entries.join("；");
}

function formatValue(value) {
  if (Array.isArray(value)) {
    return value.map(formatValue).join("、");
  }
  if (value && typeof value === "object") {
    return JSON.stringify(value);
  }
  return String(value);
}

function humanizeIdentifier(value) {
  const text = String(value || "").trim();
  if (!text) return "";
  if (displayValueLabels[text]) return displayValueLabels[text];
  return text
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replaceAll("_", " ")
    .trim();
}

function hasChinese(text) {
  return /[\u4e00-\u9fff]/.test(String(text || ""));
}

function looksLikeEnglishSentence(text) {
  const value = String(text || "").trim();
  if (!value) return false;
  const chineseChars = (value.match(/[\u4e00-\u9fff]/g) || []).length;
  if (chineseChars > 0) return false;
  const words = (value.match(/[A-Za-z]{2,}/g) || []).length;
  const asciiLetters = (value.match(/[A-Za-z]/g) || []).length;
  return words >= 3 && asciiLetters >= 16;
}

function hasValue(value) {
  if (value === null || value === undefined || value === "") return false;
  if (Array.isArray(value)) return value.length > 0;
  return true;
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function distance(a, b) {
  return Math.hypot(a.x - b.x, a.y - b.y);
}

function pointToSegmentDistance(point, start, end) {
  const dx = end.x - start.x;
  const dy = end.y - start.y;
  const lengthSq = dx * dx + dy * dy;
  if (!lengthSq) return distance(point, start);
  const t = clamp(((point.x - start.x) * dx + (point.y - start.y) * dy) / lengthSq, 0, 1);
  return distance(point, { x: start.x + t * dx, y: start.y + t * dy });
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

