"""Independent Apache-2.0 intake for RFS native-handoff/1.0.

A handoff is READY_NOT_EXECUTED, never a generated-model result. All untrusted
notes and payloads are read as data; no handoff instructions or code run here.
"""
from __future__ import annotations
import io
import re
from PIL import Image

FORMAT = 'rfs-native-handoff/1.0'
FILES = {'figure_spec':'figure-spec.json', 'image':'reference.png',
         'design':'observed-design-notes.md', 'design_intent':'design-intent.md',
         'prompt':'prompt.txt', 'handoff_instructions':'handoff.md'}


def load_handoff(folder, original_bundle, expected_spec, api):
    c=api
    root=c.no_links(folder)
    raw=c.read_local(root,'manifest.json',2_000_000)
    manifest=c.strict_json(raw)
    required={'format','status','backend','approved','figure_id','scientific_fingerprint',
              'source_candidate','files_sha256','native_file_verified','scientific_review'}
    if not isinstance(manifest,dict) or set(manifest)!=required or manifest['format']!=FORMAT:
        raise c.Rejected('Unsupported or malformed canonical RFS native handoff')
    if manifest['status']!='READY_NOT_EXECUTED' or manifest['backend']!='paper-fig':
        raise c.Rejected('Handoff must explicitly target paper-fig and remain READY_NOT_EXECUTED')
    if manifest['approved'] is not True:
        raise c.Rejected('Native handoff needs approval bound to this exact reference; no approval was inferred')
    if manifest['native_file_verified'] is not False or manifest['scientific_review']!='PENDING':
        raise c.Rejected('Handoff must not claim native execution or completed scientific review')
    checksums=manifest['files_sha256']
    if not isinstance(checksums,dict) or set(checksums)!=set(FILES.values()):
        raise c.Rejected('Handoff requires the exact current six-file three-source package')
    payloads,records={},{}
    total=0
    for role,name in FILES.items():
        contents=c.read_local(root,c.relative(name)); total+=len(contents)
        if total>100*1024*1024 or not isinstance(checksums[name],str) or c.digest(contents)!=checksums[name]:
            raise c.Rejected('Native handoff artifact hash/size mismatch: '+name)
        payloads[role]=contents
        mime='image/png' if role=='image' else 'application/json' if role=='figure_spec' else 'text/plain' if role=='prompt' else 'text/markdown'
        records[role]={'path':name,'sha256':checksums[name],'bytes':len(contents),'mime':mime}
    spec=c.validate_science(c.strict_json(payloads['figure_spec']))
    if spec['kind']!='diagram' or spec['datasets']:
        raise c.Rejected('Current RFS native-handoff intake supports its diagram contract only')
    if spec['figure_id']!=manifest['figure_id'] or c.fingerprint(spec)!=manifest['scientific_fingerprint']:
        raise c.Rejected('Handoff FigureSpec identity or scientific fingerprint changed')
    original=c.load_bundle(original_bundle,expected_spec)
    if (manifest['source_candidate']!=original['manifest']['candidate_id']
            or c.canonical(spec)!=c.canonical(original['spec'])
            or payloads['image']!=original['payloads']['image']
            or payloads['prompt']!=original['payloads']['prompt']
            or payloads['design_intent']!=original['payloads']['design']):
        raise c.Rejected('Handoff changed original candidate/reference/spec/prompt/design identity')
    try:
        notes=payloads['design'].decode('utf-8')
        for role in ('design_intent','prompt','handoff_instructions'):
            if not payloads[role].decode('utf-8').strip():
                raise c.Rejected('Handoff contains empty textual guidance')
        topics = (r'layout|composition|position|region|布局|构图|区域|位置',
                  r'object|shape|text|font|模块|对象|文字|字体|图层',
                  r'connector|arrow|edge|port|route|连线|箭头|端口',
                  r'color|palette|style|border|配色|颜色|线型|边框')
        if sum(bool(re.search(topic, notes, re.I)) for topic in topics) < 3:
            raise c.Rejected('Observed notes need layout, objects, connectors or visual style, covering at least three topics')
        if (len(notes.strip())<80 or 'fill after inspecting the candidate' in notes.lower()
                or 'status: design intentions, not an automatically validated image' in notes.lower()):
            raise c.Rejected('Observed design notes must describe an inspected image, not an unfilled intent template')
        with Image.open(io.BytesIO(payloads['image'])) as image:
            if image.format!='PNG' or image.width*image.height>64_000_000:
                raise c.Rejected('Handoff reference must be a bounded real PNG')
            image.load(); size=list(image.size)
    except (UnicodeError,OSError,ValueError,SyntaxError,Image.DecompressionBombError) as exc:
        raise c.Rejected('Invalid handoff text or decoded reference pixels') from exc
    binding={'source_candidate':manifest['source_candidate'], 'approved':manifest['approved'],
             'reference_sha256':records['image']['sha256'], 'observed_design_notes_sha256':records['design']['sha256'],
             'original_producer_manifest_sha256':original['manifest_sha256']}
    return {'root':str(root),'manifest':manifest,'manifest_sha256':c.digest(raw),'files':records,
            'source_format':FORMAT,'spec':spec,'payloads':payloads,'image_size_px':size,
            'approval_binding':binding,'original_producer':original}
