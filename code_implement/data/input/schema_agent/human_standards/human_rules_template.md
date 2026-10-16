# Schema Agent v2 Human Rules Template

## High-level Goal

Schema Agent v2 produces a universal label/property schema for textbook knowledge graphs.
It must first determine the ontological role of each candidate, then output node labels,
edge labels, and property schemas. The human base schema is an educational ontology prior,
not a closed answer set. The model should preserve its interoperability intent, evidence
policy, and reusable property shapes, while adding subject-grounded labels and predicates
when the observed textbook content cannot be expressed well by the prior.

## Controlled Discovery Principle

Newly discovered candidates default to properties when they are local phrases, chapter
headings, named examples, one-off activities, or internal attributes of a broader concept.
A candidate should be promoted to a node label only when all of the following hold: it has
a stable subject identity, multiple objects or sections will reference it, it needs
independent incoming/outgoing edges, and keeping it as a property would lose critical
relational expressiveness.

The following candidates typically remain as KnowledgePoint or Problem properties
(adapt to the actual textbook subject — mathematics, physics, chemistry, or biology):

- Formulations: formulas, theorems, laws, chemical equations, biological taxonomies.
- Procedural steps: methods, solution procedures, experimental protocols.
- Quantitative or relational structures.
- Domain-specific tools, instruments, or key concepts.
- Evidence: always EvidenceRef (text-only provenance) unless independent audit or
  cross-node reuse requires promotion.
- Figures: never a node label and never evidence. A figure intrinsically belonging to
  a node or edge must be a FigureRef under that object's `figures` property.

## Subject Schema Discovery

Schema Agent may introduce subject-level node labels and edge labels when they are reusable
across the sampled textbook content and supported by evidence. Examples of reusable subject
categories include mathematical representations, physical quantities, experimental apparatus,
chemical substances/reactions, biological structures/processes, and classification systems.
These examples are not mandatory labels; the agent must infer from the current samples.

Every promoted node label or edge label must provide:

- evidence in the positive examples or role decision reason;
- a promotion_reason explaining what relation ability would be lost if it stayed a property;
- negative_examples showing how to avoid promoting local chapter names or ordinary phrases.

Do not create labels for individual chapter titles, named historical cases, exercise numbers,
decorative activity names, or single-use examples unless they represent a reusable category.

## Role Decision Rules

Every candidate must first enter `ontology_role_decisions`. Allowed roles:

- node_label: stable identity, multi-object reuse, independent edges needed.
- edge_label: a predicate relation between two node labels, must specify source_label
  and target_label.
- node_property: a property owned by a node label, e.g. definitions, formulas,
  steps, tools, figures (under property_name=figures, value type=FigureRef).
- edge_property: a property owned by an edge label, e.g. rationale, evidence,
  figures (under property_name=figures, value type=FigureRef).
- evidence_property: provenance/audit reference. Text only (EvidenceRef).
- reject: should not enter the KG schema.

Note: images are not evidence_property. They are always node_property or edge_property
with property_name=figures and value type=FigureRef.

## Edge Label Rules

Edges must be predicate labels, not generic relation types. Each edge label must include:
predicate_id, label_zh, source_label, target_label, definition, and properties.

Edge properties must include at least `evidence` and `confidence`, and should include
`relation_label` and `rationale`.

The base educational relations `prerequisite_for`, `extends`, and `uses_method` are reusable
cross-subject priors for learning paths, conceptual progression, and problem-method links.
The agent may also add subject-specific predicates when these broad relations are too coarse.

## Evidence and Figures

EvidenceRef carries only textual context provenance from the textbook body.
It never carries image information.

IPA notes are the textualized result of a figure produced by a vision model. They are
NOT textbook body and NOT evidence. Their role is to let the text model "see" what the
image shows, so it can judge whether the image is an intrinsic part of a knowledge point,
problem, or relation (diagram, problem figure, data source chart, scene carrying the task).

Images always enter the KG through FigureRef, attached to the corresponding node/edge's
`figures` property. FigureRef is minimal: figure_id, image_path, name, description.
Core purpose is traceability (figure_id + image_path). `figures` is optional; attach it
only when a figure genuinely belongs to the node/edge.

When kg_value is low or uncertain, or the processing result indicates the figure should
not be used (failure, not audited, not extracted), the image does NOT enter `figures`.

## Universality Constraint

The human base schema and these rules must be universal, cross-textbook principles.
They may not be specialized for a specific textbook, chapter, or sample. Prompt and base
optimizations may only strengthen universal ontological principles. Subject-level labels
are allowed; textbook-local labels are not.
