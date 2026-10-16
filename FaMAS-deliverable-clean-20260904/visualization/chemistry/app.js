const DATA_ROOTS = {
  en: "./data/en",
  zh: "./data/zh",
};
const IMAGE_DATA_DIR = "./assets";

const state = {
  language: "en",
  nodes: [],
  edges: [],
  triples: [],
  nodeById: new Map(),
  edgeById: new Map(),
  selected: null,
  hovered: null,
  focusNodeId: null,
  minimapSearch: "",
  minimapHoveredNodeId: null,
  minimapPulseUntil: 0,
  leftCollapsed: false,
  explorerCollapsed: false,
  explorerExpanded: false,
  expandedRect: null,
  minimapWindowResize: null,
  detailCollapsed: false,
  detailHeight: 260,
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
  languageButton: document.querySelector("#languageButton"),
};

const ctx = els.canvas.getContext("2d");
const minimapCtx = els.minimapCanvas.getContext("2d");

const I18N = {
  en: {
    documentTitle: "Chemistry Knowledge Graph Triple Visualization",
    kgTriples: "KG Triples",
    appTitle: "Chemistry Knowledge Graph",
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
    languageButtonTitle: "Switch to Chinese",
    languageButtonText: "ZH",
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
    relationOut: "Outgoing",
    relationIn: "Incoming",
    imageDetail: "Image detail",
    close: "Close",
    figurePreview: "Figure Preview",
    statsTriples: "Triples",
    statsNodes: "Nodes",
    statsEdges: "Edges",
    focusPrefix: "Focus",
    noTriples: "No matching triples",
    chemistry: "Chemistry",
    overviewTitle: "Graph Overview",
    overviewText: "This view shows triple relations from Senior High School Chemistry Compulsory Volume 1.",
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
    },
  },
  zh: {
    documentTitle: "化学知识图谱三元组可视化",
    kgTriples: "KG Triples",
    appTitle: "化学知识图谱",
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
    languageButtonTitle: "Switch to English",
    languageButtonText: "EN",
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
    relationOut: "出向",
    relationIn: "入向",
    imageDetail: "图片详情",
    close: "关闭",
    figurePreview: "Figure Preview",
    statsTriples: "三元组",
    statsNodes: "节点",
    statsEdges: "边",
    focusPrefix: "聚焦",
    noTriples: "没有匹配的三元组",
    chemistry: "化学",
    overviewTitle: "图谱概览",
    overviewText: "当前展示《普通高中教科书·化学必修第一册》的三元组关系。",
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
      ChapterSection: "章节",
      KnowledgePoint: "知识点",
      Problem: "题目",
      Node: "节点",
    },
    fieldNames: {
      title: "标题",
      name: "名称",
      definition: "定义",
      description: "描述",
      chapter_num: "章节号",
      aliases: "别名",
      rationale: "依据",
      problem_type: "题型",
      answer: "答案",
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

const blockedNodeFields = new Set([
  "source_path",
  "confidence",
  "revision_round",
  "status",
  "audit_refs",
  "evidence",
]);

const blockedEdgeFields = new Set([
  "confidence",
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
    await loadLanguageData(state.language);
    renderStaticUi();
    renderTripleList();
    renderMinimapLegend();
    renderDetail();
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
    loadJson(`${dataRoot}/triples.json`),
    loadJson(`${dataRoot}/merged_nodes.json`),
    loadJson(`${dataRoot}/merged_edges.json`),
  ]);
  state.nodeById = new Map();
  state.edgeById = new Map();
  buildModel(tripleData, nodeData, edgeData);
  for (const node of state.nodes) {
    const previous = previousPositions.get(node.id);
    if (!previous) continue;
    Object.assign(node, previous);
  }
}

async function loadJson(url) {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`${url} ${t("readFailed")}: ${response.status}`);
  }
  return response.json();
}

function t(key) {
  return I18N[state.language]?.[key] || I18N.en[key] || key;
}

function getTypeLabel(type) {
  return I18N[state.language]?.typeLabels?.[type] || I18N.en.typeLabels[type] || type;
}

function getFieldName(key) {
  return I18N[state.language]?.fieldNames?.[key] || I18N.en.fieldNames[key] || key;
}

function applyStaticTranslations() {
  document.documentElement.lang = state.language === "zh" ? "zh-CN" : "en";
  document.title = t("documentTitle");
  document.querySelectorAll("[data-i18n]").forEach((element) => {
    element.textContent = t(element.dataset.i18n);
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
  els.languageButton.textContent = t("languageButtonText");
  refreshPanelToggleLabels();
}

async function switchLanguage() {
  const nextLanguage = state.language === "en" ? "zh" : "en";
  const selected = state.selected ? { ...state.selected } : null;
  const focusNodeId = state.focusNodeId;
  state.language = nextLanguage;
  state.search = "";
  state.minimapSearch = "";
  els.searchInput.value = "";
  els.minimapSearchInput.value = "";

  try {
    await loadLanguageData(nextLanguage);
    state.selected = selected;
    state.focusNodeId = focusNodeId && state.nodeById.has(focusNodeId) ? focusNodeId : null;
    if (state.predicate !== "all" && !state.edges.some((edge) => edge.predicate === state.predicate)) {
      state.predicate = "all";
    }
    applyStaticTranslations();
    renderStaticUi();
    renderTripleList();
    renderMinimapLegend();
    renderDetail();
    state.alpha = Math.max(state.alpha, 0.25);
    draw();
    drawMinimap();
  } catch (error) {
    showLoadError(error);
  }
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
  window.addEventListener("resize", onMinimapWindowResize);

  els.zoomInButton.addEventListener("click", () => zoomAtCenter(1.18));
  els.zoomOutButton.addEventListener("click", () => zoomAtCenter(0.85));
  els.rotateLeftButton.addEventListener("click", () => rotateGraph(-Math.PI / 18));
  els.rotateRightButton.addEventListener("click", () => rotateGraph(Math.PI / 18));
  els.resetButton.addEventListener("click", resetView);
  els.detailToggle.addEventListener("click", toggleDetailPanel);
  els.languageButton.addEventListener("click", switchLanguage);

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
    ...predicates.map((predicate) => `<option value="${escapeHtml(predicate)}">${escapeHtml(predicate)}</option>`),
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
      const quote = firstText(triple.evidence) || firstText(triple.edge?.evidence) || "";
      return `
        <button class="triple-item ${active ? "active" : ""}" type="button" data-triple-id="${escapeHtml(triple.id)}">
          <div class="triple-main">
            <strong>${escapeHtml(subject)}</strong>
            <span class="triple-arrow">${escapeHtml(triple.predicate)}</span>
            <strong>${escapeHtml(object)}</strong>
          </div>
          <div class="triple-meta">
            <span class="badge ${escapeHtml(triple.predicate)}">${escapeHtml(triple.predicate)}</span>
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
    `<span class="minimap-legend-item"><i class="dot" style="background:#4b74a8"></i>${escapeHtml(t("chemistry"))}</span>`,
    ...nodeTypes.map((type) => {
      const style = typeStyle[type] || typeStyle.Node;
      return `<span class="minimap-legend-item"><i class="dot" style="background:${style.color}"></i>${escapeHtml(getTypeLabel(type))}</span>`;
    }),
    ...predicates.map((predicate) => {
      const color = predicateStyle[predicate] || "#8d9890";
      return `<span class="minimap-legend-item"><i class="line-swatch" style="background:${color}"></i>${escapeHtml(predicate)}</span>`;
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
          <p>${escapeHtml(t("overviewText"))}</p>
          <div class="kv">
            <div class="kv-row"><span>${escapeHtml(t("statsTriples"))}</span><strong>${state.triples.length}</strong></div>
            <div class="kv-row"><span>${escapeHtml(t("statsNodes"))}</span><strong>${state.nodes.length}</strong></div>
            <div class="kv-row"><span>${escapeHtml(t("statsEdges"))}</span><strong>${state.edges.length}</strong></div>
          </div>
        </div>
        <div>${renderPredicateSummary()}</div>
      </div>
    `;
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
        ${renderKeyValues(node.props)}
        ${renderQuotes(node.evidence)}
        <p>${escapeHtml(t("relatedTriples"))}: ${related.length}</p>
      </div>
      <div>${renderFigures(node.figures)}</div>
    </div>
  `;
}

function renderEdgeDetail(edge) {
  if (!edge) return;
  els.detailPanel.innerHTML = `
    <div class="detail-grid">
      <div>
        <h2>${escapeHtml(edge.source.title)} → ${escapeHtml(edge.target.title)}</h2>
        <p><span class="badge ${escapeHtml(edge.predicate)}">${escapeHtml(edge.predicate)}</span></p>
        ${renderKeyValues(edge.props)}
        ${renderQuotes(edge.evidence)}
      </div>
      <div>${renderFigures(edge.figures)}</div>
    </div>
  `;
}

function renderTripleDetail(triple) {
  if (!triple) return;
  const figures = mergeFigures(triple.edge?.figures, triple.subject?.figures, triple.object?.figures);
  const quotes = triple.evidence.length ? triple.evidence : triple.edge?.evidence || [];
  els.detailPanel.innerHTML = `
    <div class="detail-grid">
      <div>
        <h2>${escapeHtml(triple.subject?.title || "")} → ${escapeHtml(triple.object?.title || "")}</h2>
        <p><span class="badge ${escapeHtml(triple.predicate)}">${escapeHtml(triple.predicate)}</span></p>
        <div class="kv">
          <div class="kv-row"><span>${escapeHtml(t("subjectField"))}</span><strong>${escapeHtml(triple.subject?.title || triple.raw.subject_node_id)}</strong></div>
          <div class="kv-row"><span>${escapeHtml(t("predicateField"))}</span><strong>${escapeHtml(triple.predicate)}</strong></div>
          <div class="kv-row"><span>${escapeHtml(t("objectField"))}</span><strong>${escapeHtml(triple.object?.title || triple.raw.object_node_id)}</strong></div>
          <div class="kv-row"><span>${escapeHtml(t("edgeId"))}</span><strong>${escapeHtml(triple.edgeId || "")}</strong></div>
        </div>
        ${renderQuotes(quotes)}
      </div>
      <div>${renderFigures(figures)}</div>
    </div>
  `;
}

function renderPredicateSummary() {
  const counts = state.edges.reduce((acc, edge) => {
    acc[edge.predicate] = (acc[edge.predicate] || 0) + 1;
    return acc;
  }, {});
  return `
    <div class="kv">
      ${Object.entries(counts)
        .map(([predicate, count]) => `<div class="kv-row"><span>${escapeHtml(predicate)}</span><strong>${count}</strong></div>`)
        .join("")}
    </div>
  `;
}

function renderKeyValues(props) {
  const entries = Object.entries(props || {}).filter(([, value]) => hasValue(value));
  if (!entries.length) return "";
  return `
    <div class="kv">
      ${entries
        .map(([key, value]) => {
          const label = getFieldName(key);
          return `<div class="kv-row"><span>${escapeHtml(label)}</span><strong>${escapeHtml(formatValue(value))}</strong></div>`;
        })
        .join("")}
    </div>
  `;
}

function renderQuotes(quotes) {
  const filtered = (quotes || []).filter(Boolean);
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
        .map(
          (figure) => `
            <button class="figure-card interactive" type="button"
              data-figure-src="${escapeHtml(figure.src)}"
              data-figure-title="${escapeHtml(figure.name || figure.figureId || t("figureEvidence"))}"
              data-figure-description="${escapeHtml(figure.description || t("noFigureDescription"))}"
              data-figure-id="${escapeHtml(figure.figureId || "")}">
              <img src="${escapeHtml(figure.src)}" alt="${escapeHtml(figure.description || figure.name || t("figureEvidence"))}" />
              <p>${escapeHtml(truncate(figure.description || figure.name || t("figureEvidence"), 70))}</p>
            </button>
          `,
        )
        .join("")}
    </div>
  `;
}

function selectTriple(tripleId) {
  const triple = state.triples.find((item) => item.id === tripleId);
  if (!triple) return;
  state.selected = { kind: "triple", id: triple.id };
  state.focusNodeId = null;
  centerOnNodes([triple.subject, triple.object].filter(Boolean));
  renderTripleList();
  drawMinimap();
  renderDetail();
}

function selectNode(node) {
  state.selected = { kind: "node", id: node.id };
  state.focusNodeId = node.id;
  renderTripleList();
  drawMinimap();
  renderDetail();
}

function selectEdge(edge) {
  state.selected = { kind: "edge", id: edge.id };
  state.focusNodeId = null;
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
    state.previousDetailHeight = Math.max(state.detailHeight, 180);
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
  setDetailHeight(state.previousDetailHeight || 260);
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
  els.imageModal.hidden = false;
  els.imageModalImg.src = figure.src;
  els.imageModalImg.alt = figure.description || figure.title || t("figureEvidence");
  els.imageModalTitle.textContent = figure.title || t("figureEvidence");
  els.imageModalDescription.textContent = figure.description || t("noFigureDescription");
  els.imageModalMeta.innerHTML = figure.figureId
    ? `<div class="kv-row"><span>${escapeHtml(t("figureId"))}</span><strong>${escapeHtml(figure.figureId)}</strong></div>`
    : "";
}

function closeImageModal() {
  els.imageModal.hidden = true;
  els.imageModalImg.removeAttribute("src");
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
  const label = edge.predicate;
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
    min: 150,
    max: Math.max(180, Math.min(520, stageRect.height - 220)),
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
  const quote = firstText(node.evidence);
  return `
    <h3 class="preview-title">${escapeHtml(node.title)}</h3>
    <p class="preview-subtitle">${escapeHtml(getTypeLabel(node.type))} · ${node.degree} ${escapeHtml(t("relationsUnit"))}</p>
    ${quote ? `<p class="preview-text">${escapeHtml(truncate(quote, 120))}</p>` : ""}
    ${firstFigure ? `<img class="preview-image" src="${escapeHtml(firstFigure.src)}" alt="${escapeHtml(firstFigure.description || node.title)}" />` : ""}
  `;
}

function renderEdgePreview(edge) {
  const firstFigure = edge.figures[0];
  const quote = firstText(edge.evidence);
  return `
    <h3 class="preview-title">${escapeHtml(edge.source.title)} → ${escapeHtml(edge.target.title)}</h3>
    <p class="preview-subtitle">${escapeHtml(edge.predicate)}</p>
    ${quote ? `<p class="preview-text">${escapeHtml(truncate(quote, 140))}</p>` : ""}
    ${firstFigure ? `<img class="preview-image" src="${escapeHtml(firstFigure.src)}" alt="${escapeHtml(firstFigure.description || edge.predicate)}" />` : ""}
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
  return props.title || props.name || props.problem_text || props.question || props.description || raw.node_id;
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
    .map((item) => item?.quote_or_summary)
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
      return {
        src,
        name: figure.name || "",
        description: figure.description || "",
        figureId: figure.figure_id || "",
      };
    })
    .filter(Boolean);
}

function normalizeImagePath(path) {
  if (!path || typeof path !== "string") return "";
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
    ...Object.values(node.props || {}).map(formatValue),
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
    edge.source.title,
    edge.target.title,
    ...Object.values(edge.props || {}).map(formatValue),
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

function formatValue(value) {
  if (Array.isArray(value)) {
    return value.map(formatValue).join("、");
  }
  if (value && typeof value === "object") {
    return JSON.stringify(value);
  }
  return String(value);
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
