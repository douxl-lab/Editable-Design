"""Independent Apache-2.0 OOXML checks for the paper-fig adapter.

Tests actual final package objects, not authoring declarations or screenshots.
"""
from __future__ import annotations

import io
import posixpath
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

NS = {"p": "http://schemas.openxmlformats.org/presentationml/2006/main",
      "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
      "c": "http://schemas.openxmlformats.org/drawingml/2006/chart",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
      "s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
RID = "{" + NS["r"] + "}id"


def package(path, reject):
    z = zipfile.ZipFile(path)
    entries = z.infolist()
    if len(entries) > 5000 or sum(i.file_size for i in entries) > 200 * 1024 * 1024:
        raise reject("PPTX exceeds inspection limits")
    names = [i.filename for i in entries]
    if len(names) != len(set(names)) or any(".." in n.split("/") or n.startswith("/") for n in names):
        raise reject("Ambiguous PPTX package paths")
    if any(n.endswith("vbaProject.bin") for n in names):
        raise reject("Macro content is not accepted")
    for n in names:
        if n.endswith(".rels"):
            for rel in ET.fromstring(z.read(n)):
                if rel.get("TargetMode") == "External":
                    raise reject("External PPTX relationships are not accepted")
    return z


def rels(z, part, reject):
    p = posixpath.join(posixpath.dirname(part), "_rels", posixpath.basename(part) + ".rels")
    if p not in z.namelist():
        return {}
    result = {}
    for r in ET.fromstring(z.read(p)):
        raw_target = r.get("Target", "")
        target = posixpath.normpath(raw_target.lstrip("/") if raw_target.startswith("/") else posixpath.join(posixpath.dirname(part), raw_target))
        if target.startswith("../") or target not in z.namelist() or r.get("TargetMode") == "External":
            raise reject("Missing or external native object relationship")
        result[r.get("Id")] = target
    return result


def ordered_items(plan):
    return sorted(plan["objects"] + plan.get("illustrations", []), key=lambda o: o.get("z", 0))


def categorical_snapshot(z, slide_part, objects, frozen, reject):
    """Keep original category labels as literal strings in cache and XLSX.

    Called only while finalizing newly authored candidates, never on edit input.
    This corrects deterministic runtime/snapshot numeric-string coercion without
    changing any supplied measurement or treating an imported workbook as source.
    """
    updated = {}
    from openpyxl import load_workbook
    for item in frozen["plan"]["objects"]:
        if item["role"] != "chart":
            continue
        dataset = next(d for d in frozen["spec"]["datasets"] if d["id"] == item["source_id"])
        enc = dataset["encoding"]
        expected_x = [str(row[dataset["columns"].index(enc["x"])]) for row in dataset["rows"]]
        expected_y = [row[dataset["columns"].index(enc["y"])] for row in dataset["rows"]]
        chart = objects[item["name"]].find(".//c:chart", NS)
        chart_path = rels(z, slide_part, reject).get(chart.get(RID))
        root = ET.fromstring(z.read(chart_path))
        series = root.findall(".//c:ser", NS)
        if len(series) != 1:
            raise reject("Category preservation requires the exact single supplied series")
        values = series[0].findall("c:val//c:pt", NS)
        if [float(v.find("c:v",NS).text) for v in sorted(values,key=lambda v:int(v.get("idx")))] != expected_y:
            raise reject("Cannot repair a chart whose measurement data changed")
        cat = series[0].find("c:cat", NS)
        formula = cat.find(".//c:f", NS)
        if formula is None or not formula.text:
            raise reject("New categorical chart needs its honest embedded worksheet reference")
        external = root.find("c:externalData", NS)
        workbook_path = rels(z, chart_path, reject).get(external.get(RID))
        book = load_workbook(io.BytesIO(z.read(workbook_path)), data_only=False)
        sheet = book.worksheets[0]
        if len(book.worksheets) != 1 or sheet.max_row != len(expected_x)+1 or sheet.max_column != 2:
            raise reject("Unexpected newly authored categorical workbook structure")
        if [sheet.cell(i+2,2).value for i in range(len(expected_y))] != expected_y:
            raise reject("Cannot preserve categories in a workbook whose measurements changed")
        # The snapshot helper uses column A, with a single header row.
        if not re.fullmatch(r"(?:'[^']+'|[^!]+)!\$A\$2:\$A\$" + str(len(expected_x)+1),formula.text):
            raise reject("Unexpected native category worksheet range")
        formula_text = formula.text
        cat.clear()
        ref = ET.SubElement(cat,"{"+NS["c"]+"}strRef")
        ET.SubElement(ref,"{"+NS["c"]+"}f").text = formula_text
        cache = ET.SubElement(ref,"{"+NS["c"]+"}strCache")
        ET.SubElement(cache,"{"+NS["c"]+"}ptCount",{"val":str(len(expected_x))})
        for i,label in enumerate(expected_x):
            point=ET.SubElement(cache,"{"+NS["c"]+"}pt",{"idx":str(i)})
            ET.SubElement(point,"{"+NS["c"]+"}v").text=label
            cell=sheet.cell(i+2,1); cell.value=label; cell.data_type="s"
        out=io.BytesIO(); book.save(out)
        updated[chart_path]=ET.tostring(root,encoding="utf-8",xml_declaration=True)
        updated[workbook_path]=out.getvalue()
    return updated


def order(path, frozen, reject):
    """Correct runtime cross-collection serialization order without replacing objects."""
    with package(path, reject) as z:
        part = "ppt/slides/slide1.xml"
        tree = ET.fromstring(z.read(part))
        sp = tree.find("p:cSld/p:spTree", NS)
        objects = {}
        for child in sp:
            if child.tag.rsplit("}", 1)[-1] not in {"sp", "cxnSp", "pic", "graphicFrame"}:
                continue
            nv = child.find(".//p:cNvPr", NS)
            name = nv.get("name")
            if child.tag.endswith("}pic") and name not in {o["name"] for o in frozen["plan"].get("illustrations", [])}:
                name = nv.get("descr")
                nv.set("name", name or "")
            if name in objects:
                raise reject("Duplicate runtime native names")
            objects[name] = child
        expected = [o["name"] for o in ordered_items(frozen["plan"])]
        if set(objects) != set(expected):
            raise reject("Runtime emitted missing or extra objects; cannot reorder")
        for child in objects.values():
            sp.remove(child)
        for name in expected:
            sp.append(objects[name])
        corrected = categorical_snapshot(z, part, objects, frozen, reject)
        payloads = [(i, corrected.get(i.filename, z.read(i.filename)) if i.filename != part else ET.tostring(tree, encoding="utf-8", xml_declaration=True)) for i in z.infolist()]
    tmp = Path(path).with_suffix(".ordering.tmp")
    try:
        with zipfile.ZipFile(tmp, "w") as out:
            for info, raw in payloads:
                out.writestr(info, raw)
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def wanted(value):
    return "none" if value == "none" else value.upper()


def color(element):
    if element is None or element.find("a:noFill", NS) is not None:
        return "none"
    rgb = element.find("a:solidFill/a:srgbClr", NS)
    return "#" + rgb.get("val").upper() if rgb is not None else None


def chart_check(z, slidepart, element, dataset, item, reject, default_color):
    chart = element.find(".//c:chart", NS)
    if chart is None:
        raise reject("Dataset is not a native chart")
    path = rels(z, slidepart, reject).get(chart.get(RID))
    if path is None:
        raise reject("Native chart relationship is missing")
    root = ET.fromstring(z.read(path))
    enc = dataset["encoding"]
    wanted = "barChart" if enc["chart_type"] == "bar" else "lineChart"
    area = root.find("c:chart/c:plotArea", NS)
    plot = area.find("c:" + wanted, NS)
    if plot is None or len(plot.findall("c:ser", NS)) != 1 or len([p for p in area if p.tag.endswith("Chart")]) != 1:
        raise reject("Native chart type/series changed")
    if enc["chart_type"] == "line" and any(node.get("val", "false") not in {"0", "false"} for node in plot.findall(".//c:smooth", NS)):
        raise reject("Unrequested native line interpolation is smoothed")
    series = plot.find("c:ser", NS)
    expected_color = item.get("fill", default_color)
    expected_color = "none" if expected_color == "none" else expected_color.upper()
    paint = series.find("c:spPr/a:ln", NS) if enc["chart_type"] == "line" else series.find("c:spPr", NS)
    if color(paint) != expected_color or series.findall("c:dPt",NS):
        raise reject("Native chart series color changed or gained per-point overrides")
    if enc["chart_type"] == "line" and (paint is None or abs(int(paint.get("w", "0")) - item.get("stroke_width_px", 2) * 9525) > 20):
        raise reject("Native line series stroke width changed")
    if series.find("c:cat/c:strRef/c:strCache", NS) is None:
        raise reject("Categorical labels must retain explicit string cache storage")
    def cache(key):
        points = series.findall(f"c:{key}//c:pt", NS)
        if len({p.get("idx") for p in points}) != len(points):
            raise reject("Duplicate chart cache index")
        return [p.find("c:v", NS).text for p in sorted(points, key=lambda p: int(p.get("idx")))]
    x, y = dataset["columns"].index(enc["x"]), dataset["columns"].index(enc["y"])
    expected_x, expected_y = [str(row[x]) for row in dataset["rows"]], [row[y] for row in dataset["rows"]]
    if cache("cat") != expected_x or [float(v) for v in cache("val")] != expected_y:
        raise reject("Native chart categories or quantitative cache changed")
    titles = ["".join(t.text or "" for t in axis.findall("c:title//a:t", NS)) for axis in list(area) if axis.tag.endswith(("}catAx", "}valAx"))]
    wanted_titles = [enc[ch] + (" (" + dataset["units"][enc[ch]] + ")" if dataset.get("units", {}).get(enc[ch]) else "") for ch in ("x", "y")]
    if titles != wanted_titles:
        raise reject("Native chart axis encoding changed")
    scaling = area.find("c:valAx/c:scaling", NS)
    if scaling is None or scaling.find("c:logBase",NS) is not None:
        raise reject("Unsupported native quantitative axis scale")
    actual_range = [float(scaling.find("c:"+key,NS).get("val")) if scaling.find("c:"+key,NS) is not None else None for key in ("min","max")]
    wanted_range = item.get("y_axis_range")
    if wanted_range is None and enc["chart_type"] == "bar":
        low,high = min(0,min(expected_y)),max(0,max(expected_y))
        wanted_range = [low,high] if low != high else [0,1]
    if wanted_range is not None and actual_range != wanted_range:
        raise reject("Native quantitative axis range changed or lost the bar zero baseline")
    if wanted_range is None and actual_range != [None,None]:
        raise reject("Unrequested explicit line-axis range changed")
    external = root.find("c:externalData", NS)
    if external is None:
        raise reject("Native chart has no editable embedded workbook")
    workbook = rels(z, path, reject).get(external.get(RID))
    if workbook is None:
        raise reject("Missing native chart workbook relationship")
    workbook_bytes = z.read(workbook)
    with zipfile.ZipFile(io.BytesIO(workbook_bytes)) as inner:
        if len(inner.infolist()) > 2000 or sum(i.file_size for i in inner.infolist()) > 50 * 1024 * 1024:
            raise reject("Embedded chart workbook exceeds bounded inspection limits")
    from openpyxl import load_workbook
    book = load_workbook(io.BytesIO(workbook_bytes), data_only=False, read_only=True)
    if book._external_links:
        raise reject("Chart workbook has external links")
    cells = list(book.worksheets[0].iter_rows())
    rows = [tuple(cell.value for cell in row) for row in cells]
    expected = [("Category", dataset["name"])] + list(zip(expected_x, expected_y))
    # Artifact Tool may use an empty string for its empty header cell.
    if rows != expected or any(cell.data_type == "f" for row in cells for cell in row) or any(row[0].data_type != "s" for row in cells[1:]):
        raise reject("Native chart workbook diverges from the supplied quantitative data")
    return {"chart_part": path, "workbook_part": workbook, "categories": expected_x, "values": expected_y, "actual_y_axis_range": actual_range}


def audit(path, frozen, reject):
    plan, spec = frozen["plan"], frozen["spec"]
    expected = {o["name"]: o for o in ordered_items(plan)}
    with package(path, reject) as z:
        slides = sorted(n for n in z.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n))
        if slides != ["ppt/slides/slide1.xml"]:
            raise reject("The consumer requires exactly one native figure page")
        size = ET.fromstring(z.read("ppt/presentation.xml")).find("p:sldSz", NS)
        if size is None or any(abs(int(size.get(k)) - mm * 36000) > 20 for k, mm in zip(("cx", "cy"), plan["canvas_mm"])):
            raise reject("PPTX physical canvas dimensions changed")
        part = slides[0]
        root = ET.fromstring(z.read(part))
        if color(root.find("p:cSld/p:bg/p:bgPr", NS)) != wanted(plan.get("background", "#FFFFFF")):
            raise reject("Native background changed")
        found, order_names = {}, []
        tree = root.find("p:cSld/p:spTree", NS)
        for element in tree:
            tag = element.tag.rsplit("}", 1)[-1]
            if tag in {"nvGrpSpPr", "grpSpPr"}:
                continue
            nv = element.find(".//p:cNvPr", NS)
            if nv is None or nv.get("name") not in expected or nv.get("name") in found:
                raise reject("Unknown, duplicate, or rasterized scientific object")
            if nv.get("hidden", "false") not in {"false", "0"}:
                raise reject("Native scientific object is hidden or has an invalid visibility value")
            name = nv.get("name"); item = expected[name]; order_names.append(name)
            want = "pic" if item["role"] == "independent_illustration" else "cxnSp" if item["role"] == "connector" else "graphicFrame" if item["role"] == "chart" else "sp"
            if tag != want:
                raise reject("Wrong native object representation: " + name)
            actual = {"native_tag": tag, "native_id": nv.get("id"), "pptx_part": part}
            found[name] = actual
            if item.get("text") is not None:
                text = "".join(t.text or "" for t in element.findall(".//a:t", NS))
                if text != item["text"]:
                    raise reject("Native scientific label/formula changed: " + name)
                actual["text"] = text
                runs = element.findall("p:txBody/a:p/a:r/a:rPr", NS)
                for run in runs:
                    font = run.find("a:latin", NS)
                    if font is None or font.get("typeface") != plan["font_family"]:
                        raise reject("Native text font changed")
                    if int(run.get("sz", "0")) != round(item.get("font_size_pt", 12) * 100):
                        raise reject("Native text size was not exported as requested")
                    if run.get("b", "0") != ("1" if item.get("bold", False) else "0"):
                        raise reject("Native text emphasis changed")
                    if color(run) != wanted(item.get("text_color", "#263238")):
                        raise reject("Native text color changed")
            xfrm = element.find("p:xfrm", NS) if tag == "graphicFrame" else element.find("p:spPr/a:xfrm", NS)
            if xfrm is None:
                raise reject("Missing native geometry")
            off, ext = xfrm.find("a:off", NS), xfrm.find("a:ext", NS)
            box = [int(off.get("x")), int(off.get("y")), int(ext.get("cx")), int(ext.get("cy"))]
            actual["bbox_emu"] = box
            if any(abs(v - mm * 36000) > 20 for v, mm in zip(box, item["bbox_mm"])):
                raise reject("Native object physical geometry changed: " + name)
            if tag in {"sp", "cxnSp"}:
                props = element.find("p:spPr", NS)
                geom = props.find("a:prstGeom", NS)
                wanted_geom = ("straightConnector1" if item.get("route", "straight") == "straight" else "bentConnector3") if tag == "cxnSp" else item.get("geometry", "rect") if item.get("text") is None else "rect"
                if geom is None or geom.get("prst") != wanted_geom:
                    raise reject("Native module/connector geometry changed")
                if item["role"] != "connector" and color(props) != wanted(item.get("fill", "none")):
                    raise reject("Native shape fill changed")
                line = props.find("a:ln", NS)
                if item.get("stroke", "none") != "none" and (line is None or abs(int(line.get("w", "0")) - item.get("stroke_width_px", 0) * 9525) > 1):
                    raise reject("Native stroke width changed")
                if color(line) != wanted(item.get("stroke", "none")):
                    raise reject("Native shape/connector stroke changed")
            if tag == "cxnSp":
                st, en = element.find(".//a:stCxn", NS), element.find(".//a:endCxn", NS)
                actual.update(source_native_id=st.get("id") if st is not None else None,
                              target_native_id=en.get("id") if en is not None else None,
                              source_port=st.get("idx") if st is not None else None,
                              target_port=en.get("idx") if en is not None else None)
                head, tail = element.find(".//a:headEnd", NS), element.find(".//a:tailEnd", NS)
                actual["head"] = head.get("type", "none") if head is not None else "none"
                actual["tail"] = tail.get("type", "none") if tail is not None else "none"
            elif tag == "graphicFrame":
                data = next(d for d in spec["datasets"] if d["id"] == item["source_id"])
                actual.update(chart_check(z, part, element, data, item, reject, spec["design"]["palette"][1]))
            elif tag == "pic":
                blip = element.find(".//a:blip", NS)
                target = rels(z, part, reject).get(blip.get("{" + NS["r"] + "}embed"))
                import hashlib
                if target is None or hashlib.sha256(z.read(target)).hexdigest() != item["sha256"]:
                    raise reject("Native independent illustration bytes changed")
        if set(found) != set(expected) or order_names != list(expected):
            raise reject("Missing native objects or changed cross-type layer order")
        ports = {"top": "0", "left": "1", "bottom": "2", "right": "3"}
        for name, item in expected.items():
            if item["role"] != "connector":
                continue
            actual = found[name]
            prefix = f"rfs:{spec['figure_id']}:node:"
            if actual["source_native_id"] != found[prefix + item["source"] + ":body"]["native_id"] or actual["target_native_id"] != found[prefix + item["target"] + ":body"]["native_id"]:
                raise reject("Native connector endpoints changed locked topology")
            if actual["source_port"] != ports[item["from_side"]] or actual["target_port"] != ports[item["to_side"]]:
                raise reject("Native connector ports changed the observed reference")
            if actual["head"] != "none" or actual["tail"] != ("triangle" if item["directed"] else "none"):
                raise reject("Native arrow direction differs from scientific contract")
    return found
