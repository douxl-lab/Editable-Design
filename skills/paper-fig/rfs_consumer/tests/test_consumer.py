"""Offline fail-closed regression tests, without a presentation-runtime mock."""
import copy
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import consumer as c
from protocol.interop import descriptor, assert_compatible
from fixtures import spec, bundle, plan, handoff


class BoundaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.spec = spec()
        self.manifest = bundle(self.root/'bundle', self.spec)
        self.plan = plan(self.spec, self.manifest)

    def save_manifest(self):
        c.write_json(self.root/'bundle/manifest.json', self.manifest)

    def replace_payload(self, role, raw):
        rec = self.manifest['files'][role]
        (self.root/'bundle'/rec['path']).write_bytes(raw)
        rec.update(bytes=len(raw), sha256=c.digest(raw))
        self.save_manifest()

    def rejected(self):
        with self.assertRaises(c.Rejected):
            c.load_bundle(self.root/'bundle')

    def test_valid_actual_bytes(self):
        result = c.load_bundle(self.root/'bundle', self.spec)
        self.assertEqual(result['spec'], self.spec)
        self.assertEqual(c.validate_plan(result, self.plan), [])

    def test_version_rejected(self):
        self.spec['schema_version'] = '9'
        self.replace_payload('figure_spec', json.dumps(self.spec).encode())
        self.rejected()

    def test_duplicate_json_key(self):
        with self.assertRaises(c.Rejected):
            c.strict_json('{"x":1,"x":2}')

    def test_nonfinite(self):
        with self.assertRaises(c.Rejected):
            c.strict_json('{"x":NaN}')

    def test_fingerprint_tamper(self):
        self.manifest['scientific_fingerprint'] = '0'*64
        self.save_manifest(); self.rejected()

    def test_failed_candidate_surviving_image(self):
        self.manifest['status'] = 'failed'
        self.save_manifest(); self.rejected()

    def test_failed_final_review(self):
        self.manifest['review'] = [{'status':'failed','accepted':False,'error':'review failed'}]
        self.save_manifest(); self.rejected()

    def test_review_status_requires_record(self):
        self.manifest['review_status'] = 'passed'
        self.save_manifest(); self.rejected()

    def test_unknown_review_status(self):
        self.manifest['review_status'] = 'pending'
        self.save_manifest(); self.rejected()

    def test_current_producer_completed_and_skipped(self):
        self.manifest['review_status']='skipped'; self.save_manifest(); c.load_bundle(self.root/'bundle')
        self.manifest['review_status']='completed'; self.manifest['review']=[{'review_kind':'model_visual_review','accepted':True}]
        self.save_manifest(); c.load_bundle(self.root/'bundle')

    def test_windows_case_alias(self):
        self.manifest['files']['alias'] = dict(self.manifest['files']['prompt'],path='PROMPT.TXT')
        (self.root/'bundle/PROMPT.TXT').write_bytes((self.root/'bundle/prompt.txt').read_bytes())
        self.save_manifest(); self.rejected()

    def test_reserved_manifest_alias(self):
        self.manifest['files']['alias'] = dict(self.manifest['files']['prompt'],path='MANIFEST.JSON')
        self.save_manifest(); self.rejected()

    def test_path_traversal(self):
        self.manifest['files']['prompt']['path'] = '../prompt.txt'
        self.save_manifest(); self.rejected()

    def test_symlink(self):
        target=self.root/'outside'; target.write_bytes((self.root/'bundle/prompt.txt').read_bytes())
        (self.root/'bundle/prompt.txt').unlink(); (self.root/'bundle/prompt.txt').symlink_to(target)
        self.rejected()

    def test_symlink_parent_before_dotdot_resolution(self):
        (self.root/'link').symlink_to(self.root/'bundle',target_is_directory=True)
        with self.assertRaises(c.Rejected): c.no_links(self.root/'link/../new.pptx')

    def test_valid_png_headers_broken_pixels(self):
        import struct, zlib
        from fixtures import PNG
        def chunk(kind, payload):
            return struct.pack('>I',len(payload))+kind+payload+struct.pack('>I',zlib.crc32(kind+payload)&0xffffffff)
        # Keep correct PNG signatures/chunks/CRCs, but make IDAT undecodable.
        broken = PNG[:33] + chunk(b'IDAT',b'not-a-zlib-stream') + chunk(b'IEND',b'')
        from PIL import Image
        with Image.open(io.BytesIO(broken)) as image: image.verify()
        self.replace_payload('image',broken); self.rejected()

    def test_input_spec_version(self):
        initial=copy.deepcopy(self.spec); initial['schema_version']='9'
        self.replace_payload('input_figure_spec',json.dumps(initial).encode()); self.rejected()

    def test_expected_original_science(self):
        changed=copy.deepcopy(self.spec); changed['nodes'][0]['label']='Changed'
        with self.assertRaises(c.Rejected): c.load_bundle(self.root/'bundle',changed)

    def test_protocol_changed_schema(self):
        other=descriptor(); other['figure_schema_sha256']='0'*64
        with self.assertRaises(ValueError): assert_compatible(other)

    def test_unknown_plan_field(self):
        self.plan['ignored']='data loss'
        with self.assertRaises(c.Rejected): c.validate_plan(c.load_bundle(self.root/'bundle'),self.plan)

    def test_unknown_object_not_ignored(self):
        self.plan['objects'][0]['ignored']='data loss'
        with self.assertRaises(c.Rejected): c.validate_plan(c.load_bundle(self.root/'bundle'),self.plan)

    def test_wrong_native_text(self):
        self.plan['objects'][1]['text']='Changed'
        with self.assertRaises(c.Rejected): c.validate_plan(c.load_bundle(self.root/'bundle'),self.plan)

    def test_connector_wrong_port_box(self):
        obj=next(o for o in self.plan['objects'] if o['role']=='connector'); obj['bbox_mm'][0]+=1
        with self.assertRaises(c.Rejected): c.validate_plan(c.load_bundle(self.root/'bundle'),self.plan)

    def test_whole_reference_as_illustration(self):
        rec=self.manifest['files']['image']
        self.plan['illustrations']=[{'name':'illustration:conceal','role':'independent_illustration','description':'disguised reference',**{k:rec[k] for k in ('path','sha256','mime')},'bbox_mm':[0,0,250,180],'z':99}]
        with self.assertRaises(c.Rejected): c.validate_plan(c.load_bundle(self.root/'bundle'),self.plan)

    def test_protected_local_scope(self):
        updated=copy.deepcopy(self.plan)
        repair={'scope':'local','reviewer':'test','reason':'appearance','before_plan_sha256':c.digest(c.canonical(self.plan).encode()),'changes':[{'object_name':updated['objects'][1]['name'],'text_color':'#2F6B9A'}]}
        updated['objects'][1]['text_color']='#2F6B9A'; updated['repair_history']=[repair]
        c.validate_local_repair(self.plan,updated)
        updated['objects'][0]['z']=9
        with self.assertRaises(c.Rejected): c.validate_local_repair(self.plan,updated)

    def test_explicit_bar_axis_range_kept(self):
        scientific=spec('plot'); root=self.root/'axis-bar'; manifest=bundle(root,scientific); authored=plan(scientific,manifest)
        authored['objects'][0]['y_axis_range']=[0,6]
        c.validate_plan(c.load_bundle(root),authored)
        self.assertEqual(c.chart_axis_range(scientific['datasets'][0],authored['objects'][0]),[0,6])
        authored['objects'][0]['y_axis_range']=[.2,.8]
        with self.assertRaises(c.Rejected): c.validate_plan(c.load_bundle(root),authored)

    def test_explicit_line_range_need_not_include_zero(self):
        scientific=spec('plot'); scientific['datasets'][0]['encoding']['chart_type']='line'
        root=self.root/'axis-line'; manifest=bundle(root,scientific); authored=plan(scientific,manifest)
        authored['objects'][0]['y_axis_range']=[.2,.8]
        c.validate_plan(c.load_bundle(root),authored)
        authored['objects'][0]['y_axis_range']=[.4,.8]
        with self.assertRaises(c.Rejected): c.validate_plan(c.load_bundle(root),authored)

    def test_unsupported_chart_encoding_fails(self):
        data=spec('plot'); data['datasets'][0]['encoding']['color']='condition'
        root=self.root/'plot'; manifest=bundle(root,data); p=plan(data,manifest)
        with self.assertRaises(c.Rejected): c.validate_plan(c.load_bundle(root),p)


class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name); self.spec=spec()
        self.producer=bundle(self.root/'producer',self.spec)
        self.manifest=handoff(self.root/'handoff',c.load_bundle(self.root/'producer'))
        self.plan=plan(self.spec,self.producer)
        notes_hash=self.manifest['files_sha256']['observed-design-notes.md']
        self.plan['reference_review'].update(design_sha256=notes_hash,observed_design_notes_sha256=notes_hash)
        c.write_json(self.root/'spec.json',self.spec); c.write_json(self.root/'protocol.json',descriptor())

    def load(self):
        from handoff import load_handoff
        return load_handoff(self.root/'handoff',self.root/'producer',self.spec,c)

    def save(self):
        c.write_json(self.root/'handoff/manifest.json',self.manifest)

    def prepare(self):
        c.write_json(self.root/'plan.json',self.plan)
        return c.prepare(self.root/'handoff',self.root/'plan.json',self.root/'consumer',self.root/'spec.json',self.root/'protocol.json',native_handoff_source=self.root/'producer')

    def test_preserves_three_sources_status_and_approval(self):
        receipt=self.prepare(); loaded=self.load()
        self.assertEqual(loaded['manifest'],self.manifest)
        self.assertEqual(receipt['handoff_original_status'],'READY_NOT_EXECUTED')
        self.assertTrue(receipt['approval_binding']['approved'])
        self.assertFalse(receipt['native_object_verified'])
        self.assertFalse(receipt['final_pptx_render_verified'])
        self.assertEqual((self.root/'consumer/native-handoff-snapshot/manifest.json').read_bytes(),(self.root/'handoff/manifest.json').read_bytes())
        self.assertEqual((self.root/'consumer/original-producer-snapshot/manifest.json').read_bytes(),(self.root/'producer/manifest.json').read_bytes())
        c.validate_reconstruction(self.root/'consumer')

    def test_unsupported_format(self):
        self.manifest['format']='rfs-native-handoff/9'; self.save()
        with self.assertRaises(c.Rejected): self.load()

    def test_unexecuted_status_required(self):
        self.manifest['status']='succeeded'; self.save()
        with self.assertRaises(c.Rejected): self.load()

    def test_wrong_backend(self):
        self.manifest['backend']='sivia'; self.save()
        with self.assertRaises(c.Rejected): self.load()

    def test_unapproved_reference(self):
        self.manifest['approved']=False; self.save()
        with self.assertRaises(c.Rejected): self.load()

    def test_fake_native_verified(self):
        self.manifest['native_file_verified']=True; self.save()
        with self.assertRaises(c.Rejected): self.load()

    def test_notes_hash_tamper(self):
        (self.root/'handoff/observed-design-notes.md').write_text('tampered')
        with self.assertRaises(c.Rejected): self.load()

    def test_plan_notes_binding(self):
        self.plan['reference_review']['observed_design_notes_sha256']='0'*64
        with self.assertRaises(c.Rejected): self.prepare()
        self.assertEqual(c.strict_json((self.root/'consumer/consumer-receipt.json').read_bytes())['status'],'rejected')

    def test_candidate_identity(self):
        self.manifest['source_candidate']='another-candidate'; self.save()
        with self.assertRaises(c.Rejected): self.load()

    def test_reference_identity_even_rehashed(self):
        file=self.root/'handoff/reference.png'; file.write_bytes(file.read_bytes()+b'changed-reference')
        self.manifest['files_sha256']['reference.png']=c.digest(file.read_bytes()); self.save()
        with self.assertRaises(c.Rejected): self.load()

    def test_invalid_spec_even_rehashed(self):
        file=self.root/'handoff/figure-spec.json'; bad=copy.deepcopy(self.spec); bad['schema_version']='9'
        c.write_json(file,bad); self.manifest['files_sha256'][file.name]=c.digest(file.read_bytes()); self.save()
        with self.assertRaises(c.Rejected): self.load()

    def test_approval_snapshot_tamper(self):
        self.prepare(); source=self.root/'consumer/native-handoff-snapshot/manifest.json'
        altered=c.strict_json(source.read_bytes()); altered['approved']=False; c.write_json(source,altered)
        with self.assertRaises(c.Rejected): c.validate_reconstruction(self.root/'consumer')

    def test_observed_notes_must_be_actual_three_topic_guidance(self):
        source=self.root/'handoff/observed-design-notes.md'; source.write_text('A generic unrelated observation. '*10)
        self.manifest['files_sha256'][source.name]=c.digest(source.read_bytes()); self.save()
        with self.assertRaises(c.Rejected): self.load()


if __name__=='__main__': unittest.main()
