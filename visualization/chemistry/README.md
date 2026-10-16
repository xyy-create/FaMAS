# FaMAS Chemistry KG Visualization

English | [简体中文](README-zh.md)

This directory contains the read-only static viewer for the curated FaMAS chemistry knowledge graph. It uses native HTML, CSS, JavaScript, and Canvas, with no frontend package installation or backend API.

![FaMAS chemistry KG visualization](assets/preview.png)

## Start the Viewer

The viewer loads JSON with `fetch()`, so opening `index.html` directly through `file://` is not supported. Start an HTTP server from this directory.

### Python

```bash
cd visualization/chemistry
python -m http.server 8000
```

Open `http://127.0.0.1:8000/`. No separate Node.js server is bundled in the final package.

## Interface Guide

### Triple list and filters

- Enter text in the left search field to match chapter titles, knowledge points, predicates, IDs, or evidence text.
- Use the relation menu to show all triples or only `contains`, `requires`, or `tests` relations.
- Select a triple in the list to highlight its subject, predicate edge, and object in the graph and open its details.
- Use the clear-focus button beside the relation filter to clear the current graph focus.
- Collapse or reopen the left panel with the button in its header.

### Main graph canvas

- Hover over a node or edge to show a compact preview.
- Click a node or edge to inspect it in the detail panel.
- Drag an empty canvas region to pan the graph.
- Use the mouse wheel to zoom around the pointer.
- Drag a node to reposition it temporarily; releasing it returns the node to the force layout.
- Use the toolbar `+` and `-` controls to zoom from the canvas center.
- Use the rotation controls to rotate the graph in 10-degree steps.
- Select **Reset** to restore the default view and clear the current selection.
- Select **ZH/EN** to reload the corresponding Chinese or English dataset and interface labels.

### Detail panel and FigureRefs

- The bottom detail panel shows the selected node, edge, or triple together with its properties and evidence.
- Drag the horizontal separator above the panel to change its height.
- Collapse or reopen the panel with the toolbar toggle.
- Select an interactive figure card to open the original textbook crop, FigureRef ID, title, and verified description.
- Close the figure preview with its close button, the backdrop, or the `Esc` key.

### Global minimap

- Use the minimap search field to pulse matching nodes without changing the triple filter.
- Hover over a minimap node to label the active node and its direct neighbors and emphasize their connecting edges.
- Click a minimap node to center and zoom the main graph on it, select it, and keep its one-hop context labeled.
- Click the minimap background to recenter the main graph.
- Drag the minimap background to pan the main graph.
- Use the expand button in the minimap header to open a larger overlay, then drag any edge or corner to resize it.
- Use the restore button, click the backdrop, or press `Esc` to return to the docked minimap.
- Collapse or reopen the minimap from its header.

## Dataset

Both language datasets describe the same graph IDs and topology.

| Item | Count |
| --- | ---: |
| Nodes | 85 |
| Edges | 82 |
| Triples | 82 |
| `ChapterSection` nodes | 13 |
| `KnowledgePoint` nodes | 68 |
| `Problem` nodes | 4 |
| `contains` edges | 69 |
| `requires` edges | 7 |
| `tests` edges | 6 |
| Figure images | 60 |

The release removes machine-specific `source_path` values from the viewer data. Node, edge, triple, and FigureRef identifiers remain unchanged. One node (`canon_knowledgepoint_465259580031`) is isolated in the supplied snapshot and therefore appears without an incident edge.

## Directory Layout

```text
visualization/chemistry/
├── assets/
│   ├── images/                    # 60 FigureRef image crops
│   └── preview.png                # README preview
├── data/
│   ├── en/
│   │   ├── merged_nodes.json
│   │   ├── merged_edges.json
│   │   └── triples.json
│   └── zh/
│       ├── merged_nodes.json
│       ├── merged_edges.json
│       └── triples.json
├── app.js                         # Data loading, interaction, layout, and rendering
├── index.html                     # Viewer entry point
├── minimap-helpers.js             # One-hop labels and resizable minimap geometry
├── server.js                      # Optional zero-dependency local server
└── styles.css                     # Responsive interface styles
```

## Troubleshooting

- **The page reports that data cannot be loaded:** make sure the URL begins with `http://`, not `file://`.
- **JSON or image requests return 404:** start the server inside `visualization/chemistry/`; serving a different working directory changes the relative asset paths.
- **Port 8000 or 5173 is occupied:** choose another Python port, for example `python -m http.server 8080`, or set `PORT=8080` before running `node server.js`.
- **Minimap labels look crowded:** expand or resize the minimap, then hover or select a node to isolate its one-hop context.
- **The search fields clear after switching language:** language switching reloads the corresponding dataset. The selected node, graph focus, relation filter, and canvas view are preserved when their IDs remain available.

The viewer is intentionally read-only. It does not upload, edit, persist, or export graph data and does not require a network connection after local files are loaded.
