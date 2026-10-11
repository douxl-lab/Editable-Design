"""Synthetic interoperability test inputs. No empirical or model-generated claims."""
from __future__ import annotations
import base64
import copy
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from consumer import canonical, digest, fingerprint, expected_objects

# Static 1x1 PNG is a test transport input, never a visual design or a fidelity pass.
PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4//8/AAX+Av4N70a4AAAAAElFTkSuQmCC')


def spec(kind="diagram"):
    source = "Input feeds Encoder. Encoder branches to Head A and Head B. Both heads feed Merge. Merge feeds Encoder as feedback. Encoder formula is h = f(x)."
    evidence = [{"source_id": "text", "quote": source}]
    nodes = [{"id": n, "label": label, "kind": "module", "evidence": copy.deepcopy(evidence)}
             for n, label in [("input", "Input"), ("encoder", "Encoder"), ("head-a", "Head A"), ("head-b", "Head B"), ("merge", "Merge")]]
    nodes[1]["formula"] = "h = f(x)"
    pairs = [("input", "encoder", "data_flow"), ("encoder", "head-a", "branch"), ("encoder", "head-b", "branch"),
             ("head-a", "merge", "data_flow"), ("head-b", "merge", "data_flow"), ("merge", "encoder", "feedback")]
    edges = [{"id": f"e{i}", "source": a, "target": b, "kind": k, "directed": True, "evidence": copy.deepcopy(evidence)}
             for i,(a,b,k) in enumerate(pairs)]
    edges[-1]["label"] = "feedback"
    table = {"columns": ["condition", "score"], "rows": [["Synthetic A", 0.3], ["Synthetic B", 0.7], ["Synthetic C", 0.5]]}
    content = canonical(table)
    out = {"schema_version": "1.0.0", "figure_id": "synthetic-" + kind, "kind": kind,
           "nodes": nodes if kind != "plot" else [], "edges": edges if kind != "plot" else [],
           "groups": [], "labels": [], "datasets": [],
           "sources": [{"id": "text", "kind": "user_text", "content": source, "sha256": digest(source.encode())}],
           "constraints": {"locked": True, "required_labels": [n["label"] for n in nodes] if kind != "plot" else [], "layout": [], "visual": [], "negative": ["Synthetic test only"]},
           "design": {"layout": "Synthetic native-object test", "composition": "Branches and feedback", "palette": ["#FFFFFF", "#2F6B9A", "#263238", "#EAF3F7"], "typography": "Arial", "candidate_variation": ""},
           "provenance": {"origin": "user_supplied", "scientific_verification": "unverified", "external_consumer_verified": False}}
    if kind != "diagram":
        out["sources"].append({"id": "data", "kind": "user_data", "content": content, "sha256": digest(content.encode())})
        out["datasets"] = [{"id": "data-series", "name": "Synthetic score", "source_id": "data", **table, "sha256": digest(content.encode()),
                            "units": {"score":"a.u."}, "encoding": {"x": "condition", "y": "score", "chart_type": "bar"}}]
    return out


def bundle(directory, scientific, producer=None):
    root = Path(directory)
    if producer:
        sys.path.insert(0, str(Path(producer).resolve()))
        from rfs.artifacts import export_bundle
        desc = "selected_reference"
        return export_bundle({"candidate_id": "synthetic-offline", "status": "succeeded", "review_status": "not_requested",
                              "figure_spec": scientific, "rfs_input_figure_spec": scientific,
                              "eval_image_field": desc + "_base64_png", "rfs_artifacts": {desc: {
                                  "candidate_id": "synthetic-offline", "stage": "offline_test", "provider": "test", "model": "none",
                                  "figure_spec": scientific, "prompt": "Synthetic offline test; no model call",
                                  "design_description": "Native-object interoperability test. The static PNG is only a transport placeholder and carries no visual fidelity acceptance.",
                                  "image_base64": base64.b64encode(PNG).decode(), "image_mime": "image/png"}}}, root)
    root.mkdir()
    payloads = {"image": ("image.png", PNG, "image/png"), "prompt": ("prompt.txt", b"Synthetic offline test", "text/plain"),
                "design": ("design.md", b"Synthetic transport placeholder. No visual design acceptance.", "text/markdown"),
                "figure_spec": ("figure_spec.json", (json.dumps(scientific, indent=2) + '\n').encode(), "application/json"),
                "input_figure_spec": ("figure_spec.input.json", (json.dumps(scientific, indent=2) + '\n').encode(), "application/json"),
                "plot_code": ("plot_code.py", b"raise RuntimeError('BUNDLE CODE MUST NEVER EXECUTE')\n", "text/x-python")}
    manifest = {"schema_version": "1.0.0", "candidate_id": "synthetic-offline", "status": "succeeded", "stage": "offline_test", "provider": "test", "model": "none", "description_key": "selected_reference", "options": {},
                "provenance": {"scientific_verification": "unverified", "external_consumer_verified": False, "editable_reconstruction_verified": False, "image_bytes_preserved": True, "generation": {}},
                "scientific_fingerprint": fingerprint(scientific), "review": [], "review_status": "not_requested", "error": None, "files": {}}
    for key, (name, raw, mime) in payloads.items():
        (root/name).write_bytes(raw)
        manifest["files"][key] = {"path": name, "sha256": digest(raw), "bytes": len(raw), "mime": mime}
    (root/"manifest.json").write_text(json.dumps(manifest, indent=2)+'\n')
    return manifest


def plan(scientific, manifest):
    review = {"image_sha256": manifest["files"]["image"]["sha256"], "design_sha256": manifest["files"]["design"]["sha256"], "inspected": True,
              "reviewer": "Synthetic test fixture, no visual acceptance", "composition": "Test native branches/formula/chart", "proportions": "Explicit synthetic test canvas", "palette": scientific["design"]["palette"],
              "hierarchy": "Native labels above modules", "ports": "Explicit port test", "semantic_layers": "Background modules then connections then text", "do_not_change": "All science and data",
              "node_observations": {n["id"]: {k:n[k] for k in ("label","formula") if k in n} for n in scientific["nodes"]},
              "edge_observations": {e["id"]: {k:e[k] for k in ("source","target","directed","label") if k in e} for e in scientific["edges"]},
              "other_text_observations": {}, "data_observations": {d["id"]:{"columns":d["columns"],"rows":d["rows"]} for d in scientific["datasets"]}}
    boxes = {"input":[10,65,35,25], "encoder":[60,65,40,25], "head-a":[120,25,40,25], "head-b":[120,110,40,25], "merge":[185,65,40,25]}
    objects = []
    for name, lock in expected_objects(scientific).items():
        item = {"name": name, **lock, "representation":"native", "z": 2 if lock["text"] is not None else 1, "fill":"none", "stroke":"none", "text_color":"#263238", "font_size_pt": 12, "stroke_width_px":2}
        if lock["source_kind"] == "node":
            item["bbox_mm"] = boxes[lock["source_id"]].copy()
            if lock["role"] == "body":
                item.update(fill="#EAF3F7", stroke="#2F6B9A")
            else:
                item["bbox_mm"][1] += 2 if lock["role"] == "label" else 13
                item["bbox_mm"][3] = 10
        elif lock["role"] == "connector":
            e = next(e for e in scientific["edges"] if e["id"] == lock["source_id"])
            item.update(bbox_mm=[5,5,1,1], source=e["source"], target=e["target"], directed=e["directed"], from_side="right" if e["kind"] != "feedback" else "bottom", to_side="left" if e["kind"] != "feedback" else "bottom", semantic_layer=e["kind"], route="straight", stroke="#263238", z=1.5)
        elif lock["role"] == "chart":
            item.update(bbox_mm=[20,15,210,130], fill="#2F6B9A", z=0)
        else:
            item["bbox_mm"] = [105,150,65,10]
        objects.append(item)
    for obj in objects:
        if obj["role"] == "connector":
            def port(node, side):
                x,y,w,h=boxes[node]
                return {"left":(x,y+h/2),"right":(x+w,y+h/2),"top":(x+w/2,y),"bottom":(x+w/2,y+h)}[side]
            a,b=port(obj["source"],obj["from_side"]),port(obj["target"],obj["to_side"])
            obj["bbox_mm"]=[min(a[0],b[0]),min(a[1],b[1]),abs(a[0]-b[0]),abs(a[1]-b[1])]
    return {"schema_version":"1.0.0", "scientific_fingerprint":fingerprint(scientific), "canvas_mm":[250,180], "background":"#FFFFFF", "font_family":"Arial", "reference_review":review,
            "design_change":{"reason":"Synthetic native interoperability test canvas; no visual fidelity claim", "reviewer":"test fixture"}, "objects":objects}


def handoff(directory, original):
    """Synthetic native-handoff transport fixture; E2E uses real RFS exporter."""
    from handoff import FILES, FORMAT
    root=Path(directory); root.mkdir()
    notes=("Inspected synthetic one-pixel reference: layout is only a white placeholder. "
           "No text objects, connectors or ports are visible. White is the entire color palette. "
           "The native test plan is an explicit layout change; no reference fidelity acceptance is claimed.").encode()
    manifest={'format':FORMAT,'status':'READY_NOT_EXECUTED','backend':'paper-fig','approved':True,
              'figure_id':original['spec']['figure_id'],'scientific_fingerprint':fingerprint(original['spec']),
              'source_candidate':original['manifest']['candidate_id'],'files_sha256':{},
              'native_file_verified':False,'scientific_review':'PENDING'}
    data={'figure_spec':(json.dumps(original['spec'],indent=2)+'\n').encode(),
          'image':original['payloads']['image'],'design':notes,
          'design_intent':original['payloads']['design'],'prompt':original['payloads']['prompt'],
          'handoff_instructions':b'Synthetic transport guidance only. Reconstruct native shapes from the locked contract.'}
    for role,name in FILES.items():
        (root/name).write_bytes(data[role]); manifest['files_sha256'][name]=digest(data[role])
    (root/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return manifest
