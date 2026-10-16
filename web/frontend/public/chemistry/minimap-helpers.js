(function attachMinimapHelpers(root, factory) {
  const helpers = factory();

  if (typeof module === "object" && module.exports) {
    module.exports = helpers;
  } else if (root) {
    root.MinimapHelpers = helpers;
  }
})(typeof globalThis !== "undefined" ? globalThis : this, () => {
  function nodeId(endpoint) {
    return typeof endpoint === "object" ? endpoint?.id : endpoint;
  }

  function buildOneHopContext(activeNodeId, edges) {
    const hasActiveNode = activeNodeId !== null && activeNodeId !== undefined;
    const nodeIds = new Set(hasActiveNode ? [activeNodeId] : []);
    const edgeIds = new Set();
    const relations = [];

    if (!hasActiveNode) return { activeNodeId, nodeIds, edgeIds, relations };

    for (const edge of edges || []) {
      if (!edge) continue;

      const sourceId = nodeId(edge.source);
      const targetId = nodeId(edge.target);
      if (sourceId !== activeNodeId && targetId !== activeNodeId) continue;

      const outgoing = sourceId === activeNodeId;
      const neighborId = outgoing ? targetId : sourceId;
      nodeIds.add(neighborId);
      edgeIds.add(edge.id);
      relations.push({
        edgeId: edge.id,
        predicate: edge.predicate,
        neighborId,
        direction: outgoing ? "out" : "in",
      });
    }

    return { activeNodeId, nodeIds, edgeIds, relations };
  }

  function orderNodesForRendering(nodes, activeNodeId, relatedNodeIds, emphasizedNodeIds) {
    const related = relatedNodeIds || new Set();
    const emphasized = emphasizedNodeIds || new Set();
    const rank = (node) => {
      if (node.id === activeNodeId) return 3;
      if (related.has(node.id)) return 2;
      if (emphasized.has(node.id)) return 1;
      return 0;
    };

    return (nodes || [])
      .map((node, index) => ({ node, index, rank: rank(node) }))
      .sort((a, b) => a.rank - b.rank || a.index - b.index)
      .map((item) => item.node);
  }

  function getMinimapLabelMaxWidth(expanded) {
    return expanded ? 240 : 132;
  }

  function truncateLabelText(text, maxWidth, measureText) {
    const value = String(text ?? "");
    if (!value || maxWidth <= 0) return "";
    if (measureText(value) <= maxWidth) return value;

    const ellipsis = "…";
    if (measureText(ellipsis) > maxWidth) return "";

    const characters = Array.from(value);
    let low = 0;
    let high = characters.length;
    while (low < high) {
      const middle = Math.ceil((low + high) / 2);
      const candidate = `${characters.slice(0, middle).join("")}${ellipsis}`;
      if (measureText(candidate) <= maxWidth) low = middle;
      else high = middle - 1;
    }
    return `${characters.slice(0, low).join("")}${ellipsis}`;
  }

  function orderContextLabels(labels, activeNodeId) {
    const ordinary = [];
    const active = [];
    for (const label of labels || []) {
      (label.id === activeNodeId ? active : ordinary).push(label);
    }
    return [...ordinary, ...active];
  }

  function rectangleOverlapArea(first, second) {
    const overlapWidth = Math.max(
      0,
      Math.min(first.left + first.width, second.left + second.width)
        - Math.max(first.left, second.left),
    );
    const overlapHeight = Math.max(
      0,
      Math.min(first.top + first.height, second.top + second.height)
        - Math.max(first.top, second.top),
    );
    return overlapWidth * overlapHeight;
  }

  function placeMinimapLabels(labels, options) {
    const labelItems = labels || [];
    const canvasWidth = Math.max(0, options.width);
    const canvasHeight = Math.max(0, options.height);
    const gap = options.gap ?? 6;
    const marginX = Math.min(options.margin ?? 4, canvasWidth / 2);
    const marginY = Math.min(options.margin ?? 4, canvasHeight / 2);
    const placed = [];
    const nodeBounds = labelItems.map((label) => {
      const radius = label.radius ?? 0;
      return {
        left: label.x - radius,
        top: label.y - radius,
        width: radius * 2,
        height: radius * 2,
      };
    });

    const clampLabel = (candidate, label) => ({
      ...candidate,
      left: clamp(candidate.left, marginX, Math.max(marginX, canvasWidth - marginX - label.width)),
      top: clamp(candidate.top, marginY, Math.max(marginY, canvasHeight - marginY - label.height)),
      width: label.width,
      height: label.height,
    });

    for (const label of labelItems) {
      const radius = label.radius ?? 0;
      const candidates = [
        { placement: "right", left: label.x + radius + gap, top: label.y - label.height / 2 },
        { placement: "left", left: label.x - radius - gap - label.width, top: label.y - label.height / 2 },
        { placement: "above", left: label.x - label.width / 2, top: label.y - radius - gap - label.height },
        { placement: "below", left: label.x - label.width / 2, top: label.y + radius + gap },
      ].map((candidate) => clampLabel(candidate, label));

      let best = candidates[0];
      let bestNodeOverlap = Number.POSITIVE_INFINITY;
      let bestLabelOverlap = Number.POSITIVE_INFINITY;
      for (const candidate of candidates) {
        const nodeOverlap = nodeBounds.reduce(
          (sum, bounds) => sum + rectangleOverlapArea(candidate, bounds),
          0,
        );
        const labelOverlap = placed.reduce(
          (sum, prior) => sum + rectangleOverlapArea(candidate, prior),
          0,
        );
        if (
          nodeOverlap < bestNodeOverlap
          || nodeOverlap === bestNodeOverlap && labelOverlap < bestLabelOverlap
        ) {
          best = candidate;
          bestNodeOverlap = nodeOverlap;
          bestLabelOverlap = labelOverlap;
        }
        if (nodeOverlap === 0 && labelOverlap === 0) break;
      }
      placed.push({ ...label, ...best });
    }

    return placed;
  }

  function clamp(value, minimum, maximum) {
    return Math.min(Math.max(value, minimum), maximum);
  }

  function getPanelLimits(limits) {
    const marginX = Math.min(limits.margin, limits.width / 2);
    const marginY = Math.min(limits.margin, limits.height / 2);
    const availableWidth = Math.max(0, limits.width - marginX * 2);
    const availableHeight = Math.max(0, limits.height - marginY * 2);

    return {
      marginX,
      marginY,
      maxRight: limits.width - marginX,
      maxBottom: limits.height - marginY,
      availableWidth,
      availableHeight,
      minWidth: Math.min(limits.minWidth, availableWidth),
      minHeight: Math.min(limits.minHeight, availableHeight),
    };
  }

  function createInitialPanelRect(limits) {
    const bounds = getPanelLimits(limits);
    const width = clamp(limits.width * 0.76, bounds.minWidth, bounds.availableWidth);
    const height = clamp(limits.height * 0.78, bounds.minHeight, bounds.availableHeight);

    return {
      left: (limits.width - width) / 2,
      top: (limits.height - height) / 2,
      width,
      height,
    };
  }

  function constrainPanelRect(rect, limits) {
    const bounds = getPanelLimits(limits);
    const width = clamp(rect.width, bounds.minWidth, bounds.availableWidth);
    const height = clamp(rect.height, bounds.minHeight, bounds.availableHeight);

    return {
      left: clamp(rect.left, bounds.marginX, bounds.maxRight - width),
      top: clamp(rect.top, bounds.marginY, bounds.maxBottom - height),
      width,
      height,
    };
  }

  function resizePanelRect(start, delta, direction, limits) {
    const directions = new Set(["n", "ne", "e", "se", "s", "sw", "w", "nw"]);
    if (!directions.has(direction)) {
      throw new RangeError(`Unknown resize direction: ${direction}`);
    }

    const bounds = getPanelLimits(limits);
    let left = start.left;
    let right = start.left + start.width;
    let top = start.top;
    let bottom = start.top + start.height;

    if (direction.includes("w")) {
      left = clamp(start.left + delta.x, bounds.marginX, right - bounds.minWidth);
    }
    if (direction.includes("e")) {
      right = clamp(right + delta.x, left + bounds.minWidth, bounds.maxRight);
    }
    if (direction.includes("n")) {
      top = clamp(start.top + delta.y, bounds.marginY, bottom - bounds.minHeight);
    }
    if (direction.includes("s")) {
      bottom = clamp(bottom + delta.y, top + bounds.minHeight, bounds.maxBottom);
    }

    return { left, top, width: right - left, height: bottom - top };
  }

  return {
    buildOneHopContext,
    orderNodesForRendering,
    getMinimapLabelMaxWidth,
    truncateLabelText,
    orderContextLabels,
    rectangleOverlapArea,
    placeMinimapLabels,
    createInitialPanelRect,
    constrainPanelRect,
    resizePanelRect,
  };
});
