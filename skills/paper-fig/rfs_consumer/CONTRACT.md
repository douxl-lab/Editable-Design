# Contract provenance and license

The independent adapter (`consumer.py`, `handoff.py`, `artifact.mjs`, `ooxml.py`, `render.py`,
tests and adapter documentation) is provided under this repository's
Apache-2.0 license. Its implementation continues the maintainer's private
consumer handoff; no private scientific input or output is included here.

`protocol/contract.py`, `protocol/interop.py`, the two schemas, and
`protocol/__init__.py` are copied **unmodified** from
[douxl-lab/research-figure-skill](https://github.com/douxl-lab/research-figure-skill/tree/642389edbde500446def6014fe438f32e1d5a4b1/research-figure/protocol)
commit `642389edbde500446def6014fe438f32e1d5a4b1`. They match the paired
[PaperBanana protocol](https://github.com/douxl-lab/PaperBanana/tree/c3269855ce3d5f2d3efe4434f91adb9fd1948245/rfs)
commit `c3269855ce3d5f2d3efe4434f91adb9fd1948245`. Those public protocol materials
are Apache-2.0, copyright 2026 douxl-lab where stated. The complete license is
retained at `protocol/LICENSE-APACHE-2.0`. `protocol/SOURCE.json` binds every
snapshot byte and canonical descriptor. This snapshot includes no model client,
provider SDK, credentials, or backend implementation.

Future updates must review the paired protocol source, preserve notices, copy
only these licensed contract files, update SOURCE.json, and rerun offline and
real interoperability tests. An unchanged semantic version with changed schema
or validator fingerprints is an explicit compatibility failure, not permission
to silently use an older consumer. Unrelated upstream documentation changes do
not alter the protocol descriptor.

This directory's licensing does not relicense inherited Paper Fig materials.
The original `skills/paper-fig/NOTICE.md` and repository license remain intact.
The adapter calls existing presentation-runtime and chart-workbook helpers in
their original location; it does not copy or redistribute their restricted
implementation into another project. Inherited OpenAI notices and the external
`@oai/artifact-tool` runtime retain their respective terms. The repository
Apache-2.0 license is not a blanket license for all inherited materials.

The native handoff intake independently implements the current six-file
`rfs-native-handoff/1.0` interface of
[RFS bridge.prepare_editable](https://github.com/douxl-lab/research-figure-skill/blob/642389edbde500446def6014fe438f32e1d5a4b1/research-figure/scripts/bridge.py).
It reads this Apache-2.0 source as a protocol reference, does not copy an
editable backend, and does not import or execute Sivia code. The original
handoff's READY_NOT_EXECUTED status, approval and pending native/science claims
remain intact. New consumer receipts describe actual consumer work separately.
