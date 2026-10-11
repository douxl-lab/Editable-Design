// New independent Apache-2.0 implementation. Requires the host's licensed runtime.
// No model client, generated plot-code execution, or automatic image generation.
import fs from 'node:fs/promises';
import path from 'node:path';
import { createRequire } from 'node:module';
import { pathToFileURL, fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import crypto from 'node:crypto';

const here = path.dirname(fileURLToPath(import.meta.url));
const [command, ...args] = process.argv.slice(2);
const sha = b => crypto.createHash('sha256').update(b).digest('hex');
const json = async p => JSON.parse(await fs.readFile(p, 'utf8'));
const save = async (p, v) => fs.writeFile(p, JSON.stringify(v, null, 2) + '\n');
const canonical = v => JSON.stringify(v && typeof v === 'object' ? Array.isArray(v) ? v.map(x => JSON.parse(canonical(x))) : Object.fromEntries(Object.keys(v).sort().map(k => [k, JSON.parse(canonical(v[k]))])) : v);
const axisLabel = (data, channel) => { const column = data.encoding[channel], unit = data.units?.[column]; return unit ? `${column} (${unit})` : column; };
const px = mm => mm * 96 / 25.4;
const pos = box => ({ left: px(box[0]), top: px(box[1]), width: px(box[2]), height: px(box[3]) });

async function runtime() {
  const modules = process.env.RUNTIME_NODE_MODULES;
  const resolve = modules ? createRequire(path.join(path.resolve(modules), '__rfs_runtime__.cjs')) : createRequire(import.meta.url);
  const entry = resolve.resolve('@oai/artifact-tool');
  return { api: await import(pathToFileURL(entry).href), entry };
}

async function doctor(reportPath) {
  const report = { consumer: 'paper-fig', node: process.execPath, node_version: process.version,
    supplied_node_modules: process.env.RUNTIME_NODE_MODULES ?? null,
    python: process.env.RUNTIME_PYTHON ?? null, bundled_bin: process.env.RUNTIME_BIN_DIR ?? null,
    image_generation_required_for_import: false, generation_calls: 0,
    inherited_renderer: 'bundled LibreOffice only', artifact_tool: { available: false },
    bundled_libreoffice: { available: false }, export_reopen_ready: false };
  try {
    const { api, entry } = await runtime();
    if (!api.Presentation?.create || !api.PresentationFile?.importPptx || !api.PresentationFile?.exportPptx) {
      throw new Error('Runtime lacks required presentation API');
    }
    report.artifact_tool = { available: true, entry };
    report.export_reopen_ready = true;
  } catch (error) { report.artifact_tool.error = error.message; }
  const bin = process.env.RUNTIME_BIN_DIR;
  if (bin) {
    for (const rel of ['libreoffice/program/soffice.exe', 'libreoffice/program/soffice', 'soffice.exe', 'soffice']) {
      try { await fs.access(path.join(bin, rel)); report.bundled_libreoffice = { available: true, path: path.join(bin, rel) }; break; } catch {}
    }
  }
  if (reportPath) await save(reportPath, report);
  console.log(JSON.stringify(report));
  return report;
}

async function checkedSource(dir) {
  if (!process.env.RUNTIME_PYTHON) throw new Error('Set an explicit RUNTIME_PYTHON for offline validation');
  const result = spawnSync(process.env.RUNTIME_PYTHON,
    [path.join(here, 'consumer.py'), 'validate-reconstruction', dir], { encoding: 'utf8', timeout: 30000 });
  if (result.status !== 0) throw new Error(`Reconstruction validation failed: ${result.stderr || result.error}`);
  const frozen = await json(path.join(dir, 'reconstruction.json'));
  const validated = JSON.parse(result.stdout);
  frozen.checked_plan_sha256 = validated.plan_sha256;
  frozen.checked_axis_ranges = validated.chart_axis_ranges;
  return frozen;
}

async function build(dir, output) {
  const frozen = await checkedSource(dir);
  const { api: { Presentation, PresentationFile } } = await runtime();
  await refuseOverwrite(output);
  const { spec, plan } = frozen;
  const presentation = Presentation.create({ slideSize: { width: px(plan.canvas_mm[0]), height: px(plan.canvas_mm[1]) } });
  const slide = presentation.slides.add();
  slide.background.fill = plan.background ?? '#FFFFFF';
  const byName = new Map();
  const objects = [...plan.objects].sort((a, b) => (a.z ?? 0) - (b.z ?? 0));
  // Semantic text, formulas and module surfaces are separate native shapes.
  for (const item of objects.filter(o => !['connector', 'chart'].includes(o.role))) {
    const shape = slide.shapes.add({ name: item.name,
      geometry: item.text === null ? (item.geometry ?? 'rect') : 'textbox',
      position: pos(item.bbox_mm), fill: item.fill ?? 'none',
      line: { fill: item.stroke ?? 'none', width: item.stroke_width_px ?? 0 } });
    if (item.text !== null) {
      shape.text = item.text;
      shape.text.style = { typeface: plan.font_family, fontSize: (item.font_size_pt ?? 12) * 96 / 72,
        color: item.text_color ?? '#263238', bold: item.bold ?? false, autoFit: 'none' };
    }
    byName.set(item.name, shape);
  }
  for (const item of objects.filter(o => o.role === 'connector')) {
    const source = byName.get(`rfs:${spec.figure_id}:node:${item.source}:body`);
    const target = byName.get(`rfs:${spec.figure_id}:node:${item.target}:body`);
    const connector = slide.shapes.add({ geometry: 'connector', name: item.name,
      from: source, to: target,
      fromIdx: slide.shapes.getConnectionSiteIndex(source, item.from_side),
      toIdx: slide.shapes.getConnectionSiteIndex(target, item.to_side),
      kind: item.route ?? 'straight', line: { fill: item.stroke, width: item.stroke_width_px ?? 2 },
      head: { type: 'none' }, tail: { type: item.directed ? 'triangle' : 'none', width: 'med', length: 'med' } });
    connector.name = item.name;
    byName.set(item.name, connector);
  }
  // This data conversion uses the validated supplied table; plot_code.py is ignored.
  for (const item of objects.filter(o => o.role === 'chart')) {
    const data = spec.datasets.find(d => d.id === item.source_id), enc = data.encoding;
    const ix = data.columns.indexOf(enc.x), iy = data.columns.indexOf(enc.y);
    const axis = frozen.checked_axis_ranges[item.name];
    const chart = slide.charts.add(enc.chart_type, { name: item.name, position: pos(item.bbox_mm),
      categories: data.rows.map(r => String(r[ix])), series: [{ name: data.name,
        values: data.rows.map(r => r[iy]), fill: item.fill ?? spec.design.palette[1],
        ...(enc.chart_type === 'line' ? { line: { fill: item.fill ?? spec.design.palette[1], width: item.stroke_width_px ?? 2 } } : {}) }],
      hasLegend: false, barOptions: { direction: 'column', grouping: 'clustered' },
      lineOptions: { grouping: 'standard', smooth: false, varyColors: false },
      xAxis: { title: axisLabel(data, "x"), textStyle: { typeface: plan.font_family, fontSize: 14 } },
      yAxis: { ...(axis ? { min: axis[0], max: axis[1] } : {}), title: axisLabel(data, "y"), textStyle: { typeface: plan.font_family, fontSize: 14 } } });
    chart.name = item.name;
    byName.set(item.name, chart);
  }
  for (const asset of plan.illustrations ?? []) {
    const blob = new Uint8Array(await fs.readFile(path.join(dir, frozen.source_format === 'rfs-native-handoff/1.0' ? 'native-handoff-snapshot' : 'producer-snapshot', asset.path)));
    if (sha(blob) !== asset.sha256) throw new Error('Illustration checksum changed');
    slide.images.add({ name: asset.name, blob, contentType: asset.mime, alt: asset.name,
      position: pos(asset.bbox_mm), fit: 'contain' });
  }
  slide.speakerNotes.textFrame.setText(`Source format: ${frozen.source_format}; manifest ${frozen.source_manifest_sha256}\n`
    + `Original producer manifest ${frozen.producer_manifest_sha256}\n`
    + (frozen.approval_binding ? `Handoff READY_NOT_EXECUTED source approval binding: ${JSON.stringify(frozen.approval_binding)}\n` : '')
    + `Science status: ${spec.provenance.scientific_verification}. Exact evidence matching is not scientific truth.\n`
    + spec.sources.map(s => `${s.id}: ${s.content}`).join('\n'));
  const reopened = await exportChecked(presentation, dir, output, "reconstruction.json");
  const inspection = await reopened.inspect({ kind: 'slide,shape,textbox,chart,image', maxChars: 2000000 });
  await fs.writeFile(path.join(dir, 'reopened-native-inspection.ndjson'), inspection.ndjson);
  await save(path.join(dir, 'export-receipt.json'), { runtime: '@oai/artifact-tool', output,
    output_sha256: sha(await fs.readFile(output)), reopened: true, reopened_chart_data_verified: true, generation_calls: 0,
    bundle_code_executed: false, native_object_verified: true, final_pptx_render_verified: false });
}

function validatePython(args) {
  if (!process.env.RUNTIME_PYTHON) throw new Error('Set an explicit RUNTIME_PYTHON for offline validation');
  const result = spawnSync(process.env.RUNTIME_PYTHON, [path.join(here, 'consumer.py'), ...args],
    { encoding: 'utf8', timeout: 60000 });
  if (result.status !== 0) throw new Error(`Native package check failed: ${result.stderr || result.error}`);
  return result.stdout;
}
function checkedPackage(dir, output, reconstruction) {
  validatePython(['order-pptx', output, path.join(dir, reconstruction)]);
  return JSON.parse(validatePython(['audit-pptx', output, path.join(dir, reconstruction), path.join(dir, 'native-audit.json')]));
}

async function exportChecked(presentation, dir, output, reconstruction) {
  const { api: { PresentationFile } } = await runtime();
  const unique = crypto.randomUUID();
  const candidate = `${output}.${unique}.candidate.pptx`;
  try {
    await (await PresentationFile.exportPptx(presentation)).save(candidate);
    const frozen = await json(path.join(dir, reconstruction));
    if (frozen.spec.datasets.length) {
      const snapshot = `${candidate}.workbook.pptx`;
      const receipt = path.join(dir, `${path.basename(output)}.${unique}.chart-snapshot.json`);
      const result = spawnSync(process.env.RUNTIME_PYTHON, [path.join(here, '../container_tools/materialize_literal_chart_workbooks.py'),
        candidate, snapshot, '--workspace', path.dirname(path.resolve(candidate)), '--receipt', receipt],
        { encoding: 'utf8', timeout: 60000 });
      if (result.status !== 0) throw new Error(`Complete supplied-data workbook snapshot failed: ${result.stderr || result.error}`);
      await fs.rename(snapshot, candidate);
    }
    const audited = checkedPackage(dir, candidate, reconstruction);
    const reopened = await PresentationFile.importPptx(await apiBlob(candidate));
    const inspection = await reopened.inspect({ kind: 'chart', maxChars: 2000000 });
    const records = inspection.ndjson.split('\n').filter(Boolean).map(line => JSON.parse(line));
    for (const [name, data] of Object.entries(audited.actual_native_objects)) {
      if (data.native_tag !== 'graphicFrame') continue;
      const matches = records.filter(record => record.name === name && record.kind === 'chart');
      if (matches.length !== 1) throw new Error('Reopened dataset is not one actual editable chart');
      const chart = reopened.resolve(matches[0].id), series = chart.series.getItemAt(0);
      if (JSON.stringify(series.categories) !== JSON.stringify(data.categories)
          || JSON.stringify(series.values) !== JSON.stringify(data.values)) {
        throw new Error('Reopened native chart changed category strings or quantitative values');
      }
    }
    await fs.link(candidate, output);
    await fs.rm(candidate);
    return reopened;
  } catch (error) {
    await fs.rm(candidate, { force: true });
    throw error;
  }
}

async function apiBlob(file) { const { api } = await runtime(); return api.FileBlob.load(file); }
async function refuseOverwrite(file) {
  try { await fs.access(file); throw new Error('Refusing to overwrite an existing PPTX'); }
  catch (error) { if (error.code !== 'ENOENT') throw error; }
  await fs.mkdir(path.dirname(path.resolve(file)), { recursive: true });
}

async function edit(dir, input, repairPath, output) {
  const frozen = await checkedSource(dir);
  if (frozen.spec.datasets.length) throw new Error('Chart-containing decks need a reviewed rebuild; local appearance editing must not replace workbook lineage');
  const repair = await json(repairPath);
  if (!repair.reason || !repair.reviewer || !Array.isArray(repair.changes) || !repair.changes.length) {
    throw new Error('Repair needs a reason, reviewer and bounded changes');
  }
  if (repair.scope !== 'local') throw new Error('Only bounded local appearance repairs are supported');
  validatePython(['audit-pptx', input, path.join(dir, 'reconstruction.json'), path.join(dir, 'edit-input-audit.json')]);
  if (repair.before_plan_sha256 !== frozen.checked_plan_sha256) throw new Error('Repair must bind its exact before_plan_sha256');
  await refuseOverwrite(output);
  const { api: { PresentationFile } } = await runtime();
  const presentation = await PresentationFile.importPptx(await apiBlob(input));
  const before = await presentation.inspect({ kind: 'shape,textbox,chart', maxChars: 2000000 });
  const records = before.ndjson.split('\n').filter(Boolean).map(line => JSON.parse(line));
  validatePython(['apply-repair', dir, repairPath]);
  const next = await json(path.join(dir, 'edited-reconstruction.json'));
  const edits = [];
  const seen = new Set();
  for (const change of repair.changes) {
    if (seen.has(change.object_name)) throw new Error('Duplicate repair target');
    seen.add(change.object_name);
    const item = next.plan.objects.find(o => o.name === change.object_name);
    const matches = records.filter(r => r.name === change.object_name);
    if (!item || matches.length !== 1) throw new Error('Repair target must resolve to one actual imported native object');
    if (item.role === 'connector' || item.role === 'chart') throw new Error('Connector/chart repairs require a reviewed new reconstruction plan');
    if (Object.keys(change).some(k => !['object_name', 'fill', 'text_color', 'font_size_pt', 'bbox_mm'].includes(k))) {
      throw new Error('Scientific text/formula/topology edits are forbidden');
    }
    const target = presentation.resolve(matches[0].id);
    if (change.fill !== undefined) { target.fill = change.fill; item.fill = change.fill; }
    if (change.bbox_mm !== undefined) { target.position = pos(change.bbox_mm); item.bbox_mm = change.bbox_mm; }
    if (change.text_color !== undefined) item.text_color = change.text_color;
    if (change.font_size_pt !== undefined) item.font_size_pt = change.font_size_pt;
    if (change.text_color !== undefined || change.font_size_pt !== undefined) {
      target.text.style = { typeface: next.plan.font_family, fontSize: (item.font_size_pt ?? 12) * 96 / 72,
        color: item.text_color ?? "#263238", bold: item.bold ?? false, autoFit: "none" };
    }
    edits.push({ name: item.name, resolved_anchor: matches[0].id, before: matches[0], applied: change });
  }

  // Revalidate the repaired physical layout and the immutable producer binding before save.
  const checked = spawnSync(process.env.RUNTIME_PYTHON, [path.join(here, 'consumer.py'),
    'validate-reconstruction', dir, '--file', 'edited-reconstruction.json'], { encoding: 'utf8', timeout: 30000 });
  if (checked.status !== 0) throw new Error(`Repair rejected: ${checked.stderr}`);
  const reopened = await exportChecked(presentation, dir, output, "edited-reconstruction.json");
  const after = await reopened.inspect({ kind: 'shape,textbox,chart', maxChars: 2000000 });
  await fs.writeFile(path.join(dir, 'edited-reopened-inspection.ndjson'), after.ndjson);
  await save(path.join(dir, 'edit-receipt.json'), { runtime: '@oai/artifact-tool', source_sha256: sha(await fs.readFile(input)),
    output_sha256: sha(await fs.readFile(output)), reopened_after_save: true, scope: repair.scope,
    edits, scientific_fingerprint: frozen.scientific_fingerprint, generation_calls: 0,
    bundle_code_executed: false, native_object_verified: true, final_pptx_render_verified: false });
}

try {
  if (command === 'build' || command === 'edit') {
    // Validate raw path ancestry before resolving '..' or making any writes.
    // The inherited workbook helper deliberately accepts only absolute paths.
    const absolute = JSON.parse(validatePython(['resolve-paths', '--', ...args]));
    args.splice(0, args.length, ...absolute);
  }
  if (command === 'doctor') { const result = await doctor(args[0]); if (!result.export_reopen_ready) process.exitCode = 2; }
  else if (command === 'build' && args.length === 2) await build(...args);
  else if (command === 'edit' && args.length === 4) await edit(...args);
  else throw new Error('Usage: artifact.mjs doctor [report.json] | build consumer-dir output.pptx | edit consumer-dir input.pptx repair.json output.pptx');
} catch (error) { console.error(`PAPER_FIG_ERROR: ${error.message}`); process.exitCode = 2; }
