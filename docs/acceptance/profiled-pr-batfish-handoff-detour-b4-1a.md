# Detour B4-1A profiled PR Batfish handoff acceptance

## Assurance authority handoff

Before B4-1A, the active `pr-batfish-assurance` step invoked
`.buildkite/scripts/batfish_assurance.sh` and evaluated the legacy v1
`deployments/live/promotion` plan, policy, and two-device baseline.

After B4-1A, the same single active step key invokes
`.buildkite/scripts/profiled_pr_batfish_assurance.sh`. Its canonical offline
entry point is `scripts/assurance/verify_profiled_pr_candidate.py`, and its
current explicit service stack is only `routed_underlay`. Future profiled
services extend that stack rather than replacing the Buildkite step again.

The legacy script and `deployments/live/promotion/**` remain preserved for the
legacy protected-delivery branch. The legacy script now admits only step key
`batfish-assurance`; the new script admits only `pr-batfish-assurance`.
Protected delivery remains commented out, so the legacy assurance has no active
pipeline caller.

## Offline authority and exact candidate

The PR path uses no NetBox, OpenBao, CML, device, known-hosts, SSH, or NETCONF
surface. `build_accepted_reference_allocation_evidence()` reconstructs the
accepted B3-5 NetBox evidence copy from the existing closed identity catalogs.
It is offline assurance input, not normal inventory resolution, and NetBox
remains factual authority.

The accepted source-allocation digest is:

`sha256:1352521feec8f787eb1a468c586dd3390428289314c3984416ab987a8af61b3d`

The active candidate is derived from `PROFILED_POPULATION_CATALOG` and requires
exactly these four nodes:

- `access-sw-01`;
- `core-02`;
- `edge-junos-01`; and
- `transit-ios-01`.

The B4-1 D1 digest remains:

`sha256:d25f753ef711677ccdde67bfeb7005f19759800099734a79bca1616bb77baf6b`

The final-state candidate snapshot digest remains:

`sha256:d3f545c5df160c29b82974f9d58f6ec76cbcc52037b69f63051e97a4aeed21f0`

The pinned local acceptance run used PyBatfish `2025.7.7.2423` with Batfish
`2026.07.20.3565`. It recognized all four exact nodes and passed all ten
invariants. The resulting deterministic evidence digest was:

`sha256:bef0e9e4863454f839e877d92e092fd64beec07c6562cb020ee758606a9848d3`

The candidate contains only the `10.60.0.0/30`, `10.60.0.4/30`, and
`10.60.0.8/30` routed underlay. It contains no legacy `10.6.12.0/30`, management
address, or OSPF process. The ten B4-1 parse, population, prefix, participation,
reachability, access-switch exclusion, management exclusion, and OSPF-absence
invariants pass.

`ProfiledPrAssuranceEvidence` binds the architecture identity, current explicit
service stack, accepted source digest, proposed D1, candidate digest, exact
nodes, pinned Batfish versions, invariant results, outcome, and its own digest.
Its stable artifact path is `assurance/profiled-pr-assurance.json`. The visible
annotation identifies the profiled four-device architecture and exposes only
typed review fields.

## Pipeline and safety state

There is exactly one active PR Batfish step. Its validation dependency,
PR-only condition, `ncdp-validation` queue, serialized concurrency group,
runtime-path condition, and prohibition on automatic/manual retry are
unchanged.

All four paused areas remain disabled:

- disposable CML staging;
- protected delivery, including the preserved legacy Batfish branch;
- observability runtime validation; and
- synthetic SNMPv3 runtime validation.

B4-1A performed no device, NetBox, CML, OpenBao, Terraform, host-trust,
observability, SNMP, or protected-authority mutation. It does not retire the
legacy v1 execution architecture or make profiled assurance promotion input.
