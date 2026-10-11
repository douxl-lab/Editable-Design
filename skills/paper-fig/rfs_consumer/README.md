# RFS / PaperBanana → native editable paper figure

This is an independent offline adapter for canonical FigureSpec 1.0.0 result
bundles and the current RFS `native-handoff/1.0` package. It uses the host's actual `@oai/artifact-tool`, never a mock export,
model alias, provider client, or generated `plot_code.py`. Producer bundles stay
byte-for-byte unchanged. `CONTRACT.md` records the pinned protocol and licenses.

## Capabilities and boundaries

- One-page PPTX: independent module shapes, exact editable labels and formula
  strings, groups, annotations, explicitly directed native connected edges.
  Branches and feedback are supported. Formula strings are editable text, not
  PowerPoint equation/OMML objects.
- Explicit straight or elbow connectors use named left/right/top/bottom ports.
  Arbitrary curved/waypoint routes need a reviewed implementation, not a silent
  conversion. Rectangular, rounded-rectangle and elliptical module bodies are
  supported. Z-order spans shapes, connectors, charts and illustrations.
- Native single-series categorical bar/line charts use every supplied x/y row,
  retain axis units and a zero-inclusive bar measurement axis (positive, negative
  and mixed data), and exact categories (including numeric-looking strings and
  leading zeros), and contain a real embedded XLSX
  snapshot. No aggregation, invented uncertainty, implicit series splitting,
  or execution of bundled plotting code. Unsupported encoding, including
  `color`, fails explicitly. The complete original dataset, including columns
  not plotted by its encoding, remains in the immutable producer snapshot and
  FigureSpec. Newly created chart workbook formulas describe that snapshot;
  they are not original-source workbook/formula lineage.
- Separate hash-verified raster illustrations may occupy disjoint regions.
  The selected full-page reference or original image cannot become an
  illustration, and illustrations cannot cover scientific objects.
- Local appearance edits preserve the exact scientific contract and every
  non-target object, port and layer. Text color, font size, fill and bounded
  label geometry are supported. Moving modules invalidates attached connector
  bounds unless a new plan is reviewed. Chart-containing decks require a
  reviewed rebuild so importing and re-exporting cannot silently replace
  workbook lineage. Whole-composition and scientific edits need a new plan.
- No automatic generation, uploads or model calls. A `prepared` receipt proves
  traceability only. Actual native audit, final-file rendering and human visual
  acceptance are separate evidence. Scientific correctness still requires
  domain review; a model review is not independent scientific verification.

## Runtime discovery

Read the skill's `references/implementation.md`. Use host-supplied runtime
paths or `load_workspace_dependencies` when available. Set `RUNTIME_PYTHON`
explicitly and export `RUNTIME_NODE_MODULES` if bare imports cannot resolve;
`RUNTIME_NODE` is the executable used to run the `.mjs` file. The bundled
LibreOffice and Poppler directory is `RUNTIME_BIN_DIR`. No personal paths are
hard-coded, and this adapter never downloads an opaque runtime substitute.
`requirements-adapter.txt` lists the adapter's Python dependencies. The
inherited chart snapshot helper additionally needs its bundled `lxml` parser.

Run `node rfs_consumer/artifact.mjs doctor doctor.json` from this skill folder.
Doctor distinguishes authoring/import availability from renderer availability.
An available exporter does not prove that a deck was produced or rendered.
If a capability is absent, report it and stop that stage; never create a fake
PPTX, claim image-only output is editable, or mark an unrun stage passed.

## Consume a selected result

1. Obtain the paired producer's `protocol` descriptor, original canonical
   FigureSpec, and selected result folder. RFS/PaperBanana expose protocol
   descriptor commands. The adapter's own descriptor is available with:
   `python rfs_consumer/consumer.py protocol`.
   Schema/version/validator fingerprints negotiate fail-closed. Unrelated
   upstream README changes do not affect compatibility.
2. Inspect the **actual selected image**. Write `plan.json`: scientific text,
   formulas, edges and data come from the original FigureSpec; reference pixels
   determine appearance. The written design is supplementary. Record actual
   observations and image/design hashes in `reference_review`; never copy
   expected observations as a claim that an image was inspected. Record any
   science/reference conflict with a reviewer, reason and `use_locked_spec`.
3. Prepare a new evidence folder:
   `python rfs_consumer/consumer.py prepare BUNDLE PLAN.json CONSUMER_DIR --expected-spec ORIGINAL.json --protocol PRODUCER_PROTOCOL.json`
4. Build with the real host runtime:
   `node rfs_consumer/artifact.mjs build CONSUMER_DIR NEW_FIGURE.pptx`
   As for other authoring commands, first follow the skill's one-time operation
   marker instruction. Export uses a temporary candidate, corrects deterministic runtime
   serialization (layer order and category string storage), materializes complete newly authored chart data,
   audits actual OOXML and reopens the package before publishing the output.
5. Render the audited exact final file:
   `python rfs_consumer/consumer.py render NEW_FIGURE.pptx CONSUMER_DIR/reconstruction.json NEW_RENDER_DIR`
   Only the explicitly supplied bundled renderer is used. Inspect its
   `slide-1.png`, compare with the selected reference, fix authorized issues and
   render the revised exact final file again. The render receipt binds final
   PPTX/PDF/PNG hashes and leaves `visual_review` pending: rendering success
   alone is not visual acceptance.

All directory/file placeholders above are consumer-local paths. Preparation
refuses an existing evidence directory, and building refuses an existing PPTX.
Failure receipts stay truthful. Retry with a new output/evidence name after
fixing the diagnosed issue; no failure changes producer claims to verified.
`verify-bundle BUNDLE --expected-spec ORIGINAL.json` is a read-only preflight.
`audit-pptx FILE.pptx RECONSTRUCTION.json REPORT.json` rechecks the source binding,
actual object set/text/geometry/layers/ports/arrows and chart cache/workbook.

## Consume the current RFS native handoff

RFS `scripts/bridge.py prepare_editable` emits `rfs-native-handoff/1.0` for
canonical diagrams. Use its approved `paper-fig` package directly:

`python rfs_consumer/consumer.py prepare-handoff HANDOFF PLAN.json CONSUMER_DIR --source-bundle ORIGINAL_BUNDLE --expected-spec ORIGINAL.json --protocol PRODUCER_PROTOCOL.json`

Then use the same real `artifact.mjs build`, `audit-pptx` and `render` commands
above. `--source-bundle` is the selected producer result used by RFS to create
this handoff; it binds the exact original candidate, reference pixels,
FigureSpec, prompt and generative intent. It is required because a candidate
name alone cannot establish original image identity.

The input remains `READY_NOT_EXECUTED`, with `native_file_verified: false` and
`scientific_review: PENDING`. An explicit `approved: true` bound to this exact
package is required; the consumer never infers approval. The raw manifest and
all six source files are preserved byte-for-byte in `native-handoff-snapshot`,
alongside the unchanged `original-producer-snapshot`. Consumer receipts bind
both manifests, the approval, reference and observed-notes hashes. They report
consumer execution separately without adding model/provider success fields.

For this route, `reference_review.design_sha256` and
`reference_review.observed_design_notes_sha256` both bind
`observed-design-notes.md`. Notes must describe the inspected actual image and
cover its layout, native objects/text, connectors or style. `design-intent.md`
remains separate supplementary generative intent; it is not substituted for
observed evidence. The complete original FigureSpec, all reference pixels,
notes, instructions, intent and prompt survive without executing their content.
Only the current diagram handoff version/backend is supported; unsupported
contracts, malformed sources and hash or identity mismatches fail explicitly.
Native-object correctness, science/domain review and final visual acceptance
remain separate gates.

## Plan contract

A plan contains `schema_version`, `scientific_fingerprint`, physical
`canvas_mm`, `background`, an available `font_family`, `reference_review`, and
`objects`. Each scientific entity has exact stable names from
`consumer.expected_objects(spec)`. Use `representation: native`, unchanged
`source_kind`, `source_id`, `role`, and `text`; `bbox_mm` is [x,y,width,height].
For charts, optional `y_axis_range: [min,max]` preserves an explicit observed or
requested scientific range. It must be finite, increasing and contain every
supplied measurement. Bar ranges include zero; without an explicit range the
adapter writes a real zero-inclusive data-covering range. Line axes stay
automatic unless explicitly supplied, and may use a nonzero range. The final
OOXML `valAx/scaling` bounds are audited, not inferred from axis labels.
The chart object's `fill` supplies its single series color, including the line
stroke. Line stroke width uses `stroke_width_px`; actual series colors and line
widths are audited in OOXML. Line connections are explicitly linear (`smooth: false`); unrequested native
smoothing fails audit. This protocol snapshot does not support a smoothing
request, so it is never inferred from the runtime default.

A connector's bbox describes the exact bounds of its two explicit ports and
may have zero height or width; its native line must retain those endpoints.
Use `z`, palette-bound fill/stroke/text colors, CSS-pixel stroke widths and
point font sizes. Unsupported fields fail instead of being silently dropped.

`reference_review` needs image/design hashes, `inspected`, reviewer,
composition, proportions, palette, hierarchy, ports, semantic layers,
do-not-change boundaries, and actual node/edge/other-text/data observations.
`design_change` requires reason and reviewer when intentionally changing
canvas proportion. It does not permit changing scientific facts.
`tests/fixtures.py` shows a programmatic **synthetic test plan**, not a design
reference or an example of legitimate image-review evidence.

A repair JSON has `scope: local`, `reason`, `reviewer`, exact
`before_plan_sha256` from `validate-reconstruction`, and a bounded `changes`
array. Each change names `object_name` and only the supported appearance fields.
Run `artifact.mjs edit CONSUMER_DIR INPUT.pptx REPAIR.json NEW_OUTPUT.pptx`.
Both imported input and final output are scientifically/native audited;
producer/source numbers are retained by Python's exact JSON snapshot rather
than round-tripped through JavaScript number serialization.

## Tests

Offline boundary tests:
`python -m unittest discover -s rfs_consumer/tests -v`

Real end-to-end check (no runtime mock):
`python rfs_consumer/tests/run_e2e.py --output NEW_EVIDENCE_DIR --paperbanana PAPERBANANA_CHECKOUT --research-figure RFS_CHECKOUT`

The real check requires installed artifact-tool, explicit `RUNTIME_PYTHON` and
bundled `RUNTIME_BIN_DIR`. It calls the actual pinned PaperBanana bundle
exporter without model calls, checks protocol bytes, exports/reopens/renders
branch/feedback/formula, native bar/line charts, and a bounded appearance edit.
When `--research-figure` is supplied it also calls the real RFS
`prepare_editable`, consumes its native handoff and builds/reopens/renders it.
It rejects real-package label/formula, endpoint, port, arrow, object-set,
z-order, quantitative cache/workbook and edit-input tampering. Data is clearly
synthetic. Its 1px PNG is only a transport placeholder and **cannot establish
visual fidelity**. Tests do not ship private user inputs or generated outputs.
