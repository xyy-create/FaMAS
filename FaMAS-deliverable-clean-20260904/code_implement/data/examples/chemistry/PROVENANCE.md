# Chemistry Example Provenance

## Scope

This directory contains a curated chemistry snapshot from a FaMAS execution. Operational run identifiers, timestamps, and machine-specific paths were removed for the double-blind release. Node, edge, triple, FigureRef, evidence, and confidence content were otherwise preserved.

The snapshot contains 85 nodes, 82 edges, and 82 triples.

## Included artifacts

| Artifact | SHA-256 |
| --- | --- |
| Textbook PDF | `8926092A955E006625958A09B6D4C582FA07A5F18F837EA45E9FC0000D18352A` |
| Schema `final_schema.json` | `3931B738EF6C351F78263A98BE798E93FDAE0C5576AFAAD4CB3989294AEE593B` |
| KG `merged_nodes.json` | `2F39CDDE0521C6597489306E23C8EA6CFDCA168983F00362DF18027B13E24233` |
| KG `merged_edges.json` | `41B325C122D6807915E266B7C9C16BBBF15F0175D531B1673320596AB8A91F2B` |
| KG `triples.json` | `F38FAADE468FE2E257FD5A1B5A39C0ECB528B6951D6D7693E295C2FF1E9BA970` |

## Release normalization

- The top-level KG `run_id` is `chemistry_example`.
- Historical source paths are repository relative and use the neutral run component `ipa_chemistry_example`.
- Windows path separators and machine-specific prefixes are not present.
- Entity, relation, triple, and FigureRef identifiers are unchanged so cross-file references remain valid.

## Historical schema note

The copied historical Schema reports `textbook_profile.subject: math` and retains inherited mathematics-oriented descriptions, the `MathToolRef` type reference, and mathematics examples. These values are artifacts of the source execution and are retained as evidence of the actual output. This file is not a subject-correct chemistry Schema template. A new full FaMAS run invokes the Schema Agent to generate and publish a run-specific Schema.
