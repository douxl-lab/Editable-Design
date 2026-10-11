"""Independent, offline RFS 1.0.0 consumer. No model calls or bundle code execution.

New implementation for Editable-Design, licensed under the repository Apache-2.0.
Schema snapshots are attributed in CONTRACT.md. Validation proves traceability,
not the truth of scientific claims or automatic interpretation of reference pixels.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import io
import json
import math
import re
import stat
import sys
import zipfile
from pathlib import Path, PureWindowsPath
from xml.etree import ElementTree as ET

from jsonschema import Draft202012Validator
from PIL import Image

from protocol.contract import (validate_figure_spec, scientific_fingerprint, RFSValidationError)
from protocol.interop import descriptor, assert_compatible

HERE = Path(__file__).parent
COLLECTIONS = ("nodes", "edges", "groups", "labels", "datasets")
MAX_FILE = 32 * 1024 * 1024
NS = {"p": "http://schemas.openxmlformats.org/presentationml/2006/main",
      "a": "http://schemas.openxmlformats.org/drawingml/2006/main"}


class Rejected(ValueError):
    pass


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def fingerprint(spec):
    # The sole presentation-only exclusion is design. Constraints/provenance stay locked.
    return scientific_fingerprint(spec)


def strict_json(data):
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise Rejected(f"Duplicate JSON key: {key}")
            value[key] = item
        return value
    try:
        value = json.loads(data, object_pairs_hook=pairs,
                           parse_constant=lambda v: (_ for _ in ()).throw(Rejected(f"Nonfinite JSON: {v}")))
        canonical(value)
        return value
    except (ValueError, TypeError, RecursionError) as exc:
        raise Rejected(f"Invalid finite JSON: {exc}") from exc


def no_links(path):
    absolute = Path(path).absolute()
    for part in (absolute, *absolute.parents):
        if part.exists() or part.is_symlink():
            info = part.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise Rejected(f"Symlink/reparse point is forbidden: {part}")
    return absolute


def relative(value):
    if (not isinstance(value, str) or not value or "\\" in value or ":" in value or "\0" in value
            or value.startswith("/") or PureWindowsPath(value).drive):
        raise Rejected("Expected a safe relative POSIX path")
    for part in value.split("/"):
        if (part in ("", ".", "..") or part.rstrip(" .") != part
                or re.match(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", part, re.I)):
            raise Rejected("Path traversal/reserved filename is forbidden")
    return value


def read_local(root, value, limit=MAX_FILE):
    path = no_links(root / relative(value))
    if not path.is_relative_to(root) or not path.is_file():
        raise Rejected(f"Missing local regular artifact: {value}")
    if path.stat().st_size > limit:
        raise Rejected(f"Artifact exceeds size limit: {value}")
    return path.read_bytes()


def read_absolute(path, limit=MAX_FILE):
    path = no_links(path)
    if not path.is_file() or path.stat().st_size > limit:
        raise Rejected("Expected a bounded regular local input file")
    return path.read_bytes()


def schema_check(value, filename):
    schema = strict_json((HERE / "protocol" / "schemas" / filename).read_bytes())
    errors = sorted(Draft202012Validator(schema).iter_errors(value), key=lambda e: str(list(e.path)))
    if errors:
        raise Rejected(f"{filename} {list(errors[0].path)}: {errors[0].message}")


def validate_science(spec):
    try:
        return validate_figure_spec(spec)
    except RFSValidationError as exc:
        raise Rejected(str(exc)) from exc


def validate_review(manifest):
    reviews, status = manifest["review"], manifest["review_status"]
    if status not in {"not_requested", "skipped", "completed", "passed", "accepted", "succeeded"}:
        raise Rejected("Unaccepted or unknown producer review status")
    if status in {"not_requested", "skipped"} and reviews:
        raise Rejected("Review history contradicts not_requested status")
    if status not in {"not_requested", "skipped"} and not reviews:
        raise Rejected("Successful review status requires its actual review history")
    if reviews:
        final = reviews[-1]
        if final.get("status") in {"failed", "invalid", "error", "cancelled"} or final.get("accepted") is False or final.get("error"):
            raise Rejected("Final review failed despite successful candidate status")


def load_bundle(bundle, expected_spec=None):
    root = no_links(bundle)
    manifest_bytes = read_local(root, "manifest.json", 2_000_000)
    manifest = strict_json(manifest_bytes)
    schema_check(manifest, "manifest-v1.schema.json")
    if manifest["status"] != "succeeded" or manifest["error"] is not None or manifest["review_status"] in ("failed", "invalid"):
        raise Rejected("Failed candidate cannot be reconstructed, even if an image survives")
    validate_review(manifest)
    if len(manifest["files"]) > 32:
        raise Rejected("Too many bundle artifacts")
    payloads, paths = {}, set()
    total = 0
    for key, record in manifest["files"].items():
        name = relative(record["path"])
        if name.casefold() in paths or name.casefold() == "manifest.json":
            raise Rejected("Duplicate artifact path")
        paths.add(name.casefold())
        contents = read_local(root, name)
        total += len(contents)
        if total > 100 * 1024 * 1024:
            raise Rejected("Bundle exceeds size limit")
        if len(contents) != record["bytes"] or digest(contents) != record["sha256"]:
            raise Rejected(f"Producer artifact size/hash mismatch: {key}")
        payloads[key] = contents
    spec = validate_science(strict_json(payloads["figure_spec"]))
    if fingerprint(spec) != manifest["scientific_fingerprint"]:
        raise Rejected("Scientific fingerprint mismatch")
    if manifest["provenance"]["scientific_verification"] != spec["provenance"]["scientific_verification"]:
        raise Rejected("Producer science verification fields disagree")
    try:
        with Image.open(io.BytesIO(payloads["image"])) as image:
            image.verify()
            if Image.MIME.get(image.format) != manifest["files"]["image"]["mime"]:
                raise Rejected("Image MIME mismatch")
        with Image.open(io.BytesIO(payloads["image"])) as image:
            if image.width * image.height > 64_000_000:
                raise Rejected("Reference image exceeds 64 million pixels")
            image.load()
            image_size = list(image.size)
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError) as exc:
        raise Rejected("Invalid reference image") from exc
    if expected_spec is not None and fingerprint(validate_science(expected_spec)) != fingerprint(spec):
        raise Rejected("Result changed caller's original scientific contract")
    if "input_figure_spec" in payloads:
        initial = validate_science(strict_json(payloads["input_figure_spec"]))
        if fingerprint(initial) != fingerprint(spec):
            raise Rejected("Input/output scientific contracts disagree")
        if expected_spec is not None and canonical(initial) != canonical(expected_spec):
            raise Rejected("Input spec is not the caller's exact supplied snapshot")
    metadata = manifest["provenance"]["generation"].get("compiler_metadata", {})
    if not isinstance(metadata, dict):
        raise Rejected("Compiler metadata must be an object")
    if metadata.get("prompt_sha256") is not None and metadata["prompt_sha256"] != digest(payloads["prompt"]):
        raise Rejected("Selected prompt does not match compiler submission")
    for key in ("design", "prompt"):
        if manifest["files"][key]["mime"] not in {"text/plain", "text/markdown"}:
            raise Rejected("Prompt/design must be text artifacts")
        if not payloads[key].decode("utf-8").strip():
            raise Rejected(f"Empty {key} artifact")
    return {"root": str(root), "manifest": manifest, "manifest_sha256": digest(manifest_bytes),
            "files": manifest["files"], "source_format": "paperbanana-rfs-result/1.0",
            "spec": spec, "image_size_px": image_size, "payloads": payloads}


def expected_objects(spec):
    result = {}
    def add(kind, entity, role, text=None):
        name = f"rfs:{spec['figure_id']}:{kind}:{entity['id']}:{role}"
        result[name] = {"source_kind": kind, "source_id": entity["id"], "role": role, "text": text}
    for node in spec["nodes"]:
        add("node", node, "body"); add("node", node, "label", node["label"])
        if "formula" in node:
            add("node", node, "formula", node["formula"])
    for edge in spec["edges"]:
        add("edge", edge, "connector")
        if "label" in edge:
            add("edge", edge, "label", edge["label"])
    for group in spec["groups"]:
        add("group", group, "body"); add("group", group, "label", group["label"])
    for label in spec["labels"]:
        add("label", label, "label", label["text"])
    for dataset in spec["datasets"]:
        add("dataset", dataset, "chart")
    return result


def compare_reference(spec, review):
    # Explicit observations from an inspected selected image, not claimed OCR/vision.
    conflicts = []
    expected = {n["id"]: {k: n[k] for k in ("label", "formula") if k in n} for n in spec["nodes"]}
    if review.get("node_observations") != expected:
        conflicts.append({"kind": "node_labels_or_formulas", "expected": expected, "observed": review.get("node_observations")})
    expected = {e["id"]: {k: e[k] for k in ("source", "target", "directed", "label") if k in e} for e in spec["edges"]}
    if review.get("edge_observations") != expected:
        conflicts.append({"kind": "edge_direction_or_label", "expected": expected, "observed": review.get("edge_observations")})
    expected = {e["id"]: e["label"] for e in spec["groups"]} | {e["id"]: e["text"] for e in spec["labels"]}
    if review.get("other_text_observations") != expected:
        conflicts.append({"kind": "group_or_label_text", "expected": expected, "observed": review.get("other_text_observations")})
    expected = {d["id"]: {"columns": d["columns"], "rows": d["rows"]} for d in spec["datasets"]}
    if review.get("data_observations") != expected:
        conflicts.append({"kind": "reference_data", "expected": expected, "observed": review.get("data_observations")})
    return conflicts


def chart_axis_range(dataset, item):
    if "y_axis_range" in item:
        return item["y_axis_range"]
    if dataset["encoding"]["chart_type"] != "bar":
        return None
    col = dataset["columns"].index(dataset["encoding"]["y"])
    values = [row[col] for row in dataset["rows"]]
    low, high = min(0, min(values)), max(0, max(values))
    return [low, high] if low != high else [0, 1]


def validate_plan(bundle, plan):
    spec, files = bundle["spec"], bundle["files"]
    allowed = {"schema_version", "scientific_fingerprint", "canvas_mm", "background", "font_family",
               "reference_review", "science_conflict_resolution", "objects", "illustrations", "design_change", "repair_history"}
    if not isinstance(plan, dict) or set(plan) - allowed:
        raise Rejected("Unknown reconstruction plan field")
    if not isinstance(plan.get("font_family"), str) or not plan["font_family"].strip():
        raise Rejected("Explicit available font family is required")
    if plan.get("schema_version") != "1.0.0" or plan.get("scientific_fingerprint") != fingerprint(spec):
        raise Rejected("Plan version/science binding mismatch")
    review = plan.get("reference_review", {})
    if (review.get("image_sha256") != files["image"]["sha256"]
            or review.get("design_sha256") != files["design"]["sha256"]
            or review.get("inspected") is not True or not review.get("reviewer")):
        raise Rejected("Selected image/design must have an explicit hash-bound inspection")
    if bundle.get("source_format") == "rfs-native-handoff/1.0" and review.get("observed_design_notes_sha256") != files["design"]["sha256"]:
        raise Rejected("Native handoff plan must bind its actual observed-design-notes hash")
    for item in ("composition", "proportions", "palette", "hierarchy", "ports", "semantic_layers", "do_not_change"):
        if not review.get(item):
            raise Rejected(f"Reference review must describe {item}")
    conflicts = compare_reference(spec, review)
    resolution = plan.get("science_conflict_resolution")
    if conflicts and (not isinstance(resolution, dict) or resolution.get("use_locked_spec") is not True
                      or not resolution.get("reason") or not resolution.get("reviewer")):
        raise Rejected("Scientific/reference conflict requires a recorded resolution using the locked FigureSpec")
    width, height = plan.get("canvas_mm", [0, 0])
    if any(type(v) not in (int, float) or not math.isfinite(v) or v <= 0 for v in (width, height)):
        raise Rejected("Physical canvas dimensions must be finite positive mm")
    ratio = bundle["image_size_px"][0] / bundle["image_size_px"][1]
    if abs(width / height - ratio) > 0.01 and not plan.get("design_change"):
        raise Rejected("Reference canvas proportion changed without a design-change record")
    if plan.get("design_change") and (not plan["design_change"].get("reason") or not plan["design_change"].get("reviewer")):
        raise Rejected("Composition change requires reason and reviewer")
    expected = expected_objects(spec)
    objects = plan.get("objects", [])
    if {o.get("name") for o in objects} != set(expected) or len(objects) != len(expected):
        raise Rejected("Every semantic module/text/formula/edge must be a separate stable native object")
    edges = {e["id"]: e for e in spec["edges"]}
    if not isinstance(review["palette"], list) or any(not re.fullmatch(r"#[0-9a-fA-F]{6}", c) for c in review["palette"]):
        raise Rejected("Inspected palette must contain RGB hex colors")
    allowed_colors = set(review["palette"]) | {"none"}
    if plan.get("background", "#FFFFFF") not in allowed_colors:
        raise Rejected("Background absent from inspected reference palette")
    for item in objects:
        allowed_item = {"name", "source_kind", "source_id", "role", "text", "representation", "z", "bbox_mm",
                        "fill", "stroke", "stroke_width_px", "text_color", "font_size_pt", "bold", "geometry",
                        "source", "target", "directed", "from_side", "to_side", "semantic_layer", "route", "y_axis_range"}
        if set(item) - allowed_item:
            raise Rejected("Unsupported object field must not be silently ignored")
        for field, lower in (("z", -1000000), ("stroke_width_px", 0), ("font_size_pt", 1)):
            val = item.get(field, 0 if field == "z" else 12 if field == "font_size_pt" else 0)
            if type(val) not in (int, float) or not math.isfinite(val) or val < lower or val > 1000000:
                raise Rejected("Invalid object style numeric value")
        if item.get("geometry", "rect") not in {"rect", "roundRect", "ellipse"}:
            raise Rejected("Unsupported editable module geometry")
        if "bold" in item and type(item["bold"]) is not bool:
            raise Rejected("Bold style must be a boolean")
        if "y_axis_range" in item and item["role"] != "chart":
            raise Rejected("Axis ranges are valid only for native chart objects")
        lock = expected[item["name"]]
        if any(item.get(key) != value for key, value in lock.items()):
            raise Rejected(f"Object changes scientific content: {item['name']}")
        if item.get("representation") != "native":
            raise Rejected("Scientific objects must remain native editable objects")
        box = item.get("bbox_mm")
        if (not isinstance(box, list) or len(box) != 4 or any(type(v) not in (int, float) or not math.isfinite(v) for v in box)
                or min(box[0:2]) < 0 or (min(box[2:4]) < 0 or sum(box[2:4]) <= 0 if item["role"] == "connector" else min(box[2:4]) <= 0) or box[0] + box[2] > width + .01 or box[1] + box[3] > height + .01):
            raise Rejected("Object outside physical canvas")
        for color in ("fill", "stroke", "text_color"):
            if item.get(color, "none") not in allowed_colors:
                raise Rejected("Object color absent from inspected reference palette")
        if item["role"] == "connector":
            edge = edges[item["source_id"]]
            if item.get("source") != edge["source"] or item.get("target") != edge["target"] or item.get("directed") != edge["directed"]:
                raise Rejected("Connector changes scientific direction")
            if item.get("route", "straight") not in {"straight", "elbow"}:
                raise Rejected("Unsupported connector route")
            if item.get("from_side") not in ("left", "right", "top", "bottom") or item.get("to_side") not in ("left", "right", "top", "bottom") or not item.get("semantic_layer"):
                raise Rejected("Connectors require explicit ports and semantic layer")
            bodies = {o["source_id"]: o for o in objects if o["source_kind"] == "node" and o["role"] == "body"}
            def port(body, side):
                x, y, w, h = body["bbox_mm"]
                return {"left": (x,y+h/2), "right":(x+w,y+h/2), "top":(x+w/2,y), "bottom":(x+w/2,y+h)}[side]
            a, b = port(bodies[item["source"]], item["from_side"]), port(bodies[item["target"]], item["to_side"])
            wanted = [min(a[0],b[0]), min(a[1],b[1]), abs(a[0]-b[0]), abs(a[1]-b[1])]
            if any(abs(v-w) > .001 for v,w in zip(box,wanted)):
                raise Rejected("Connector bounds must describe the exact explicit port endpoints")
        if item["role"] == "chart":
            dataset = next(d for d in spec["datasets"] if d["id"] == item["source_id"])
            enc = dataset.get("encoding", {})
            if enc.get("chart_type") not in ("bar", "line") or not {"x", "y"} <= enc.keys() or set(enc) != {"x", "y", "chart_type"}:
                raise Rejected("This consumer supports explicit single-series bar/line encoding only; never executes plot_code")
            xidx = dataset["columns"].index(enc["x"])
            if any(type(row[xidx]) not in (str,int,float) or (isinstance(row[xidx], str) and not row[xidx]) for row in dataset["rows"]):
                raise Rejected("Chart categories require explicit nonempty strings or finite numeric labels")
            idx = dataset["columns"].index(enc["y"])
            if any(type(row[idx]) not in (int, float) or not math.isfinite(row[idx]) for row in dataset["rows"]):
                raise Rejected("Chart y values must be supplied finite numeric data")
            bounds = chart_axis_range(dataset, item)
            if bounds is not None:
                values = [row[idx] for row in dataset["rows"]]
                if (not isinstance(bounds,list) or len(bounds) != 2
                        or any(type(v) not in (int,float) or not math.isfinite(v) for v in bounds)
                        or bounds[0] >= bounds[1] or min(values) < bounds[0] or max(values) > bounds[1]):
                    raise Rejected("Explicit axis range must be finite, increasing and contain every supplied measurement")
                if enc["chart_type"] == "bar" and not bounds[0] <= 0 <= bounds[1]:
                    raise Rejected("Bar chart measurement axes must include zero")
    # Full-page scientific references cannot masquerade as independent illustration assets.
    asset_names = set()
    for asset in plan.get("illustrations", []):
        if set(asset) - {"name", "role", "description", "path", "sha256", "mime", "bbox_mm", "z"}:
            raise Rejected("Unknown illustration field")
        if asset.get("role") != "independent_illustration" or not asset.get("description"):
            raise Rejected("Raster assets require a separate illustration role")
        if not isinstance(asset.get("name"), str) or not asset["name"].startswith("illustration:") or asset["name"] in asset_names:
            raise Rejected("Independent illustrations require unique stable names")
        asset_names.add(asset["name"])
        path = relative(asset["path"])
        role = next((k for k, r in files.items() if r["path"] == path), None)
        record = files.get(role)
        if (role in {None, "image", "original_image"} or record["sha256"] != asset.get("sha256")
                or record["mime"] != asset.get("mime") or not record["mime"].startswith("image/")):
            raise Rejected("Illustration must be a separately hash-verified bundle asset")
        box = asset.get("bbox_mm")
        if (not isinstance(box, list) or len(box) != 4 or any(type(v) not in (int, float) or not math.isfinite(v) for v in box)
                or min(box[:2]) < 0 or min(box[2:]) <= 0 or box[0] + box[2] > width or box[1] + box[3] > height):
            raise Rejected("Invalid illustration bounds")
        if box[2] * box[3] > .5 * width * height:
            raise Rejected("Illustration cannot cover the reference canvas")
        for obj in objects:
            a, b = box, obj["bbox_mm"]
            if min(a[0]+a[2], b[0]+b[2]) > max(a[0],b[0]) and min(a[1]+a[3],b[1]+b[3]) > max(a[1],b[1]):
                raise Rejected("Independent illustration must not conceal scientific objects")
        try:
            with Image.open(io.BytesIO(bundle["payloads"][role])) as im:
                if im.width * im.height > 64_000_000 or Image.MIME.get(im.format) != asset["mime"]:
                    raise Rejected("Invalid illustration MIME or size")
                im.load()
        except (OSError, ValueError, SyntaxError, Image.DecompressionBombError) as exc:
            raise Rejected("Illustration cannot decode") from exc
    return conflicts


def validate_local_repair(original, updated):
    history = updated.get("repair_history", [])
    if not history:
        raise Rejected("Edited plan requires a bounded repair history")
    current = copy.deepcopy(original)
    allowed = {"fill", "text_color", "font_size_pt", "bbox_mm"}
    for repair in history:
        if (repair.get("scope") != "local" or not repair.get("reason") or not repair.get("reviewer")
                or not isinstance(repair.get("changes"), list) or not repair["changes"]):
            raise Rejected("Only explicit local appearance repairs are supported")
        if repair.get("before_plan_sha256") != digest(canonical(current).encode()):
            raise Rejected("Repair is not bound to its exact preceding plan")
        seen = set()
        for change in repair["changes"]:
            name = change.get("object_name")
            if name in seen or set(change) - allowed - {"object_name"}:
                raise Rejected("Repair changes unknown or scientific fields")
            seen.add(name)
            target = next((o for o in current["objects"] if o["name"] == name), None)
            if target is None or target["role"] in {"connector", "chart"}:
                raise Rejected("Repair target needs a reviewed new plan")
            for key in allowed & set(change):
                target[key] = change[key]
        current.setdefault("repair_history", []).append(repair)
    if canonical(current) != canonical(updated):
        raise Rejected("Local repair changed protected composition, topology, ports, or z-order")


def prepare(bundle_path, plan_path, out, expected_spec_path, protocol_path, *, native_handoff_source=None):
    target = no_links(out)
    if target.exists():
        raise Rejected("Refusing to overwrite consumer evidence directory")
    target.mkdir(parents=True)
    receipt = {"consumer": "Editable-Design paper-fig RFS consumer", "schema_version": "1.0.0",
               "status": "rejected", "producer_unchanged": True, "generation_calls": 0,
               "bundle_code_executed": False, "native_object_verified": False,
               "final_pptx_render_verified": False, "reopen_edit_verified": False}
    try:
        assert_compatible(strict_json(read_absolute(protocol_path, 1_000_000)))
        expected_spec = validate_science(strict_json(read_absolute(expected_spec_path, 4_000_000)))
        if native_handoff_source is None:
            bundle = load_bundle(bundle_path, expected_spec)
        else:
            from handoff import load_handoff
            bundle = load_handoff(bundle_path, native_handoff_source, expected_spec, sys.modules[__name__])
        receipt["source_format"] = bundle["source_format"]
        receipt["source_manifest_sha256"] = bundle["manifest_sha256"]
        original = bundle.get("original_producer", bundle)
        receipt["producer_manifest_sha256"] = original["manifest_sha256"]
        receipt["producer_files"] = original["files"]
        if "approval_binding" in bundle:
            receipt["approval_binding"] = bundle["approval_binding"]
            receipt["handoff_original_status"] = bundle["manifest"]["status"]
        receipt["scientific_verification"] = bundle["spec"]["provenance"]["scientific_verification"]
        plan_bytes = read_absolute(plan_path, 4_000_000)
        plan = strict_json(plan_bytes)
        receipt["plan_sha256"] = digest(plan_bytes)
        receipt["scientific_conflicts"] = compare_reference(bundle["spec"], plan.get("reference_review", {}))
        conflicts = validate_plan(bundle, plan)
        write_json(target / "plan.original.json", plan)
        frozen = {"protocol": descriptor(), "original_plan_sha256": digest(canonical(plan).encode()), "spec": bundle["spec"], "plan": plan, "source_format": bundle["source_format"], "source_manifest_sha256": bundle["manifest_sha256"], "producer_manifest_sha256": original["manifest_sha256"],
                  "scientific_fingerprint": fingerprint(bundle["spec"]), "image_sha256": bundle["files"]["image"]["sha256"],
                  "scientific_conflicts": conflicts}
        if "approval_binding" in bundle:
            frozen["approval_binding"] = bundle["approval_binding"]
        write_json(target / "reconstruction.json", frozen)
        write_json(target / "object-map.json", {"units": "mm", "css_px_per_mm": 96 / 25.4,
                   "emu_per_mm": 36000, "canvas_mm": plan["canvas_mm"], "objects": plan["objects"],
                   "note": "Authoring intent only. audit-pptx checks actual exported native XML separately."})
        # Preserve producer artifacts byte for byte in a read-only conceptual snapshot;
        # the independent consumer receipt never changes producer provenance flags.
        snapshot_name = "native-handoff-snapshot" if native_handoff_source is not None else "producer-snapshot"
        snapshot = target / snapshot_name
        snapshot.mkdir()
        for key, data in bundle["payloads"].items():
            path = snapshot / bundle["files"][key]["path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        (snapshot / "manifest.json").write_bytes(read_local(Path(bundle["root"]), "manifest.json"))
        if native_handoff_source is not None:
            original_snapshot = target / "original-producer-snapshot"
            original_snapshot.mkdir()
            for key, data in original["payloads"].items():
                path = original_snapshot / original["files"][key]["path"]
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            (original_snapshot / "manifest.json").write_bytes(read_local(Path(original["root"]), "manifest.json"))
        receipt["status"] = "prepared"
        receipt["limitations"] = ["Exact evidence matching is traceability, not scientific truth.",
                                   "Reference semantics depend on the recorded visual inspection.",
                                   "Preparation alone proves neither native PPTX objects nor final-file rendering."]
    except Exception as exc:
        receipt["error"] = str(exc)
        raise
    finally:
        write_json(target / "consumer-receipt.json", receipt)
    return receipt


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def load_snapshot(root, frozen):
    source_format = frozen.get("source_format", "paperbanana-rfs-result/1.0")
    if source_format == "paperbanana-rfs-result/1.0":
        return load_bundle(root / "producer-snapshot")
    if source_format != "rfs-native-handoff/1.0":
        raise Rejected("Unknown native reconstruction source format")
    from handoff import load_handoff
    bundle = load_handoff(root / "native-handoff-snapshot", root / "original-producer-snapshot", frozen["spec"], sys.modules[__name__])
    if bundle["approval_binding"] != frozen.get("approval_binding"):
        raise Rejected("Original reference approval or observed-notes binding changed")
    return bundle


def validate_reconstruction(directory, filename="reconstruction.json"):
    root = no_links(directory)
    frozen = strict_json(read_local(root, filename))
    assert_compatible(frozen.get("protocol"))
    original_plan = strict_json(read_local(root, "plan.original.json"))
    if digest(canonical(original_plan).encode()) != frozen["original_plan_sha256"]:
        raise Rejected("Original reconstruction plan binding changed")
    if filename == "reconstruction.json" and canonical(original_plan) != canonical(frozen["plan"]):
        raise Rejected("Prepared plan changed without a bounded repair record")
    bundle = load_snapshot(root, frozen)
    original = bundle.get("original_producer", bundle)
    if original["manifest_sha256"] != frozen["producer_manifest_sha256"] or bundle["manifest_sha256"] != frozen.get("source_manifest_sha256", frozen["producer_manifest_sha256"]) or fingerprint(bundle["spec"]) != frozen["scientific_fingerprint"]:
        raise Rejected("Producer binding or scientific fingerprint changed")
    if canonical(bundle["spec"]) != canonical(frozen["spec"]):
        raise Rejected("Consumer must preserve the complete producer FigureSpec")
    validate_plan(bundle, frozen["plan"])
    if filename != "reconstruction.json":
        validate_local_repair(original_plan, frozen["plan"])
    return {"status": "valid_reconstruction", "scientific_fingerprint": frozen["scientific_fingerprint"], "plan_sha256": digest(canonical(frozen["plan"]).encode()),
            "chart_axis_ranges": {o["name"]: chart_axis_range(next(d for d in frozen["spec"]["datasets"] if d["id"] == o["source_id"]), o)
                                  for o in frozen["plan"]["objects"] if o["role"] == "chart"}}


def apply_repair(directory, repair_path):
    root = no_links(directory)
    validate_reconstruction(root)
    frozen = strict_json(read_local(root, "reconstruction.json"))
    repair = strict_json(read_absolute(repair_path, 4_000_000))
    next_plan = copy.deepcopy(frozen["plan"])
    for change in repair.get("changes", []):
        item = next((o for o in next_plan["objects"] if o["name"] == change.get("object_name")), None)
        if item is None:
            raise Rejected("Unknown local repair target")
        item.update({k:v for k,v in change.items() if k != "object_name"})
    next_plan.setdefault("repair_history", []).append(repair)
    validate_local_repair(frozen["plan"], next_plan)
    validate_plan(load_snapshot(root, frozen), next_plan)
    frozen["plan"] = next_plan
    write_json(root / "edited-reconstruction.json", frozen)
    return validate_reconstruction(root, "edited-reconstruction.json")


def audit_pptx(pptx, reconstruction):
    reconstruction = no_links(reconstruction)
    validate_reconstruction(reconstruction.parent, reconstruction.name)
    frozen = strict_json(reconstruction.read_bytes())
    from ooxml import audit
    found = audit(no_links(pptx), frozen, Rejected)
    return {"native_object_verified": True, "pptx_sha256": digest(Path(pptx).read_bytes()),
            "object_count": len(found), "actual_native_objects": found,
            "final_pptx_render_verified": False,
            "note": "OOXML audit proves objects, text, topology, ports and encoded chart data, not pixel fidelity or scientific truth."}


def order_pptx(pptx, reconstruction):
    reconstruction = no_links(reconstruction)
    validate_reconstruction(reconstruction.parent, reconstruction.name)
    from ooxml import order
    order(no_links(pptx), strict_json(reconstruction.read_bytes()), Rejected)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    resolved = sub.add_parser("resolve-paths"); resolved.add_argument("paths", nargs="+")
    sub.add_parser("protocol")
    check = sub.add_parser("verify-bundle"); check.add_argument("bundle"); check.add_argument("--expected-spec")
    prep = sub.add_parser("prepare"); prep.add_argument("bundle"); prep.add_argument("plan"); prep.add_argument("out"); prep.add_argument("--expected-spec", required=True); prep.add_argument("--protocol", required=True)
    hp = sub.add_parser("prepare-handoff"); hp.add_argument("handoff"); hp.add_argument("plan"); hp.add_argument("out"); hp.add_argument("--source-bundle", required=True); hp.add_argument("--expected-spec", required=True); hp.add_argument("--protocol", required=True)
    repaired = sub.add_parser("apply-repair"); repaired.add_argument("directory"); repaired.add_argument("repair")
    rendered = sub.add_parser("render"); rendered.add_argument("pptx"); rendered.add_argument("reconstruction"); rendered.add_argument("out")
    ordered = sub.add_parser("order-pptx"); ordered.add_argument("pptx"); ordered.add_argument("reconstruction")
    audit = sub.add_parser("audit-pptx"); audit.add_argument("pptx"); audit.add_argument("reconstruction"); audit.add_argument("report")
    valid = sub.add_parser("validate-reconstruction"); valid.add_argument("directory"); valid.add_argument("--file", default="reconstruction.json")
    args = parser.parse_args()
    try:
        if args.command == "resolve-paths":
            print(canonical([str(no_links(p).resolve(strict=False)) for p in args.paths]))
        elif args.command == "protocol":
            print(canonical(descriptor()))
        elif args.command == "verify-bundle":
            bundle = load_bundle(args.bundle, strict_json(Path(args.expected_spec).read_bytes()) if args.expected_spec else None)
            print(canonical({"status": "verified_bundle", "manifest_sha256": bundle["manifest_sha256"],
                             "scientific_verification": bundle["spec"]["provenance"]["scientific_verification"]}))
        elif args.command == "prepare":
            print(canonical(prepare(args.bundle, args.plan, args.out, args.expected_spec, args.protocol)))
        elif args.command == "prepare-handoff":
            print(canonical(prepare(args.handoff, args.plan, args.out, args.expected_spec, args.protocol, native_handoff_source=args.source_bundle)))
        elif args.command == "validate-reconstruction":
            print(canonical(validate_reconstruction(args.directory, args.file)))
        elif args.command == "apply-repair":
            print(canonical(apply_repair(args.directory,args.repair)))
        elif args.command == "render":
            from render import render
            print(canonical(render(args.pptx, args.reconstruction, args.out, Rejected, audit_pptx)))
        elif args.command == "order-pptx":
            order_pptx(args.pptx, args.reconstruction)
        else:
            result = audit_pptx(args.pptx, args.reconstruction)
            write_json(args.report, result); print(canonical(result))
    except (Rejected, RFSValidationError, OSError, KeyError, TypeError, ValueError) as exc:
        print(f"RFS_REJECTED: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
