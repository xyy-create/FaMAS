"""Standardization and triple generation for KG Extraction MAS."""

from __future__ import annotations

import hashlib
import re
from typing import Any, Sequence

from .models import ExtractionSectionContext, make_stable_id


def extract_domain_profile(
    *,
    schema: dict[str, Any],
    contexts: Sequence[ExtractionSectionContext],
    node_pack: dict[str, Any],
    edge_pack: dict[str, Any],
) -> dict[str, Any]:
    """Extract textbook/domain profile for SdA.

    Args:
        schema: Published KG schema.
        contexts: Source contexts.
        node_pack: VA-approved node pack.
        edge_pack: VA-approved edge pack.

    Returns:
        Domain profile used by SdA prompt and reports.
    """

    first = contexts[0] if contexts else None
    return {
        "schema_textbook_profile": schema.get("textbook_profile", {}),
        "textbook_profile": first.textbook_profile if first else {},
        "section_titles": [context.section_metadata.get("chapter_title", "") for context in contexts],
        "node_labels": sorted({node.get("label", "") for node in node_pack.get("nodes", []) if node.get("label")}),
        "edge_predicates": sorted({edge.get("predicate", "") for edge in edge_pack.get("edges", []) if edge.get("predicate")}),
    }


def normalize_domain_name(name: str) -> str:
    """Normalize OCR and spacing artifacts in domain names.

    Args:
        name: Raw node name or alias.

    Returns:
        Normalized name.
    """

    return re.sub(r"\s+", "", str(name)).strip()


def _node_identity(node: dict[str, Any]) -> str:
    props = node.get("properties", {})
    if node.get("label") == "KnowledgePoint":
        return normalize_domain_name(props.get("name", ""))
    if node.get("label") == "Problem":
        problem_text = normalize_domain_name(str(props.get("problem_text", "")))
        return hashlib.sha256(problem_text.encode("utf-8")).hexdigest()[:16]
    if node.get("label") == "ChapterSection":
        return normalize_domain_name(props.get("title", "") + props.get("source_path", ""))
    return normalize_domain_name(node.get("node_id", ""))


def _figure_key(figure: dict[str, Any]) -> str:
    return str(figure.get("image_path") or figure.get("figure_id") or "").strip()


def _append_unique_figures(figures: list[dict[str, Any]], seen: set[str], candidates: Any) -> None:
    for figure in candidates or []:
        if not isinstance(figure, dict):
            continue
        key = _figure_key(figure)
        if key and key not in seen:
            figures.append(figure)
            seen.add(key)


def canonicalize_nodes(
    nodes: Sequence[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, str], dict[str, Any]]:
    """Canonicalize and deduplicate VA-approved nodes.

    Args:
        nodes: Node items from node pack.

    Returns:
        Tuple of merged nodes, original-to-canonical ID map, and audit.
    """

    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for node in nodes:
        groups.setdefault((str(node.get("label", "")), _node_identity(node)), []).append(node)
    merged = []
    id_map: dict[str, str] = {}
    audit = {"canonical_mappings": [], "conflicts": []}
    for (label, identity), items in groups.items():
        canonical_id = make_stable_id(f"canon_{label.lower()}", [label, identity])
        base = dict(items[0])
        base["original_node_ids"] = [item["node_id"] for item in items]
        base["node_id"] = canonical_id
        props = dict(base.get("properties", {}))
        aliases = set(props.get("aliases", []) or [])
        evidence = list(props.get("evidence", []) or [])
        figures: list[dict[str, Any]] = []
        figure_keys: set[str] = set()
        _append_unique_figures(figures, figure_keys, props.get("figures", []))
        for item in items:
            id_map[item["node_id"]] = canonical_id
            iprops = item.get("properties", {})
            name = iprops.get("name") or iprops.get("title") or iprops.get("problem_text")
            if name:
                aliases.add(normalize_domain_name(str(name)))
            for ev in iprops.get("evidence", []) or []:
                if ev not in evidence:
                    evidence.append(ev)
            _append_unique_figures(figures, figure_keys, iprops.get("figures", []))
            audit["canonical_mappings"].append(
                {
                    "original_id": item["node_id"],
                    "canonical_id": canonical_id,
                    "reason": "exact normalized identity match",
                }
            )
        if label == "KnowledgePoint" and props.get("name"):
            props["name"] = normalize_domain_name(props["name"])
        props["aliases"] = sorted(alias for alias in aliases if alias)
        props["evidence"] = evidence
        if figures:
            props["figures"] = figures
        else:
            props.pop("figures", None)
        base["properties"] = props
        merged.append(base)
    return merged, id_map, audit


def dedupe_edges(
    edges: Sequence[dict[str, Any]],
    node_id_map: dict[str, str],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Deduplicate edges after node canonicalization.

    Args:
        edges: VA-approved edge candidates.
        node_id_map: Original node ID to canonical node ID map.

    Returns:
        Tuple of merged edges and edge audit.
    """

    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for edge in edges:
        source = node_id_map.get(edge.get("source_node_id"), edge.get("source_node_id"))
        target = node_id_map.get(edge.get("target_node_id"), edge.get("target_node_id"))
        groups.setdefault((str(edge.get("predicate", "")), str(source), str(target)), []).append(edge)
    merged = []
    audit = {"deduped_edges": []}
    for (predicate, source, target), items in groups.items():
        edge_id = make_stable_id(f"canon_edge_{predicate}", [predicate, source, target])
        base = dict(items[0])
        base["edge_id"] = edge_id
        base["source_node_id"] = source
        base["target_node_id"] = target
        base["original_edge_ids"] = [item["edge_id"] for item in items]
        props = dict(base.get("properties", {}))
        evidence = list(props.get("evidence", []) or [])
        figures: list[dict[str, Any]] = []
        figure_keys: set[str] = set()
        _append_unique_figures(figures, figure_keys, props.get("figures", []))
        confidence = float(props.get("confidence", 0))
        for item in items:
            iprops = item.get("properties", {})
            for ev in iprops.get("evidence", []) or []:
                if ev not in evidence:
                    evidence.append(ev)
            _append_unique_figures(figures, figure_keys, iprops.get("figures", []))
            confidence = max(confidence, float(iprops.get("confidence", 0)))
        props["evidence"] = evidence
        if figures:
            props["figures"] = figures
        else:
            props.pop("figures", None)
        props["confidence"] = confidence
        base["properties"] = props
        merged.append(base)
        audit["deduped_edges"].append({"canonical_id": edge_id, "original_ids": base["original_edge_ids"]})
    return merged, audit


def build_triples(
    merged_edges: Sequence[dict[str, Any]],
    *,
    run_id: str,
) -> dict[str, Any]:
    """Build triples JSON from standardized edges.

    Args:
        merged_edges: Canonicalized and deduplicated edges.
        run_id: Current KG extraction run ID.

    Returns:
        `kg.triples.v1` package.
    """

    triples = []
    for edge in merged_edges:
        triple_id = make_stable_id(
            f"triple_{edge.get('predicate', 'edge')}",
            [edge.get("predicate", ""), edge.get("source_node_id", ""), edge.get("target_node_id", ""), edge.get("edge_id", "")],
        )
        triples.append(
            {
                "triple_id": triple_id,
                "subject_node_id": edge.get("source_node_id"),
                "predicate": edge.get("predicate"),
                "object_node_id": edge.get("target_node_id"),
                "edge_id": edge.get("edge_id"),
                "evidence": edge.get("properties", {}).get("evidence", []),
                "confidence": edge.get("properties", {}).get("confidence", 0),
            }
        )
    return {"schema_version": "kg.triples.v1", "run_id": run_id, "triples": triples}


def standardize_kg(
    *,
    node_pack: dict[str, Any],
    edge_pack: dict[str, Any],
    schema: dict[str, Any],
    contexts: Sequence[ExtractionSectionContext],
    run_id: str,
) -> dict[str, Any]:
    """Run deterministic SdA standardization.

    Args:
        node_pack: VA-approved node package.
        edge_pack: VA-approved edge package.
        schema: Published KG schema.
        contexts: Section contexts.
        run_id: Current run ID.

    Returns:
        Dict containing merged nodes, merged edges, triples, domain profile, and audit.
    """

    nodes, node_id_map, node_audit = canonicalize_nodes(node_pack.get("nodes", []))
    edges, edge_audit = dedupe_edges(edge_pack.get("edges", []), node_id_map)
    return {
        "merged_nodes": {"schema_version": "kg.merged_nodes.v1", "run_id": run_id, "nodes": nodes},
        "merged_edges": {"schema_version": "kg.merged_edges.v1", "run_id": run_id, "edges": edges},
        "triples": build_triples(edges, run_id=run_id),
        "domain_profile": extract_domain_profile(schema=schema, contexts=contexts, node_pack=node_pack, edge_pack=edge_pack),
        "audit": {"node_id_map": node_id_map, "node_audit": node_audit, "edge_audit": edge_audit},
    }
