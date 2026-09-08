# Profile-reuse interface-description acceptance

## Acceptance and evidence boundary

**CAP-PROFILE-REUSE-WRITE — ACCEPTED by explicit user sign-off.** Passing tests
and implementation merge did not confer acceptance; the user's explicit
sign-off did. The [capability ledger](../roadmap.md#cap-profile-reuse-write--profile-reuse-interface-description-admission)
is authoritative for state. This record preserves the reviewed implementation
and controlled runtime evidence; no runtime operation was repeated for this
documentation closeout.

Implementation merged through [PR #153](https://github.com/Atheer-Kareem/network-change-delivery-platform/pull/153),
“CAP-PROFILE-REUSE-WRITE: explicit IOSv/IOSvL2 interface-description admission,”
at main commit `2bdfd1a82add97ff74cf21426519c5c9ff9588f2`. The final controlled
proof used clean `main`, equal to `origin/main`, at that commit.

The capability proves that compatible IOSv and IOSvL2 profiles reuse the
established Cisco lifecycle only after explicit reviewed operation admission,
while preserving interface protection, stale-plan rejection, one-shot execution,
targeted inverse/recovery and uncertainty contracts. A real device configuration
write was not required and was not manufactured solely for acceptance.

## Implementation and merged validation

`interface_description` has exactly four explicit reviewed operation/profile
admissions:

- `cat8000v_iosxe`
- `vjunos_router`
- `iosv_159_3_m12`
- `iosvl2_2020`

Family compatibility remains separate from explicit operation admission.
Population membership grants no write authority; future profiles are not
automatically admitted. No additional operation was introduced.

IOSv/IOSvL2 use IOS and the existing `ansible_network_cli` transport, `cisco_ios`
adapter and renderer, `cisco_ios_facts` collector, SSH/22, and
`cisco_targeted_inverse`, with no confirmed timeout or confirmation operation.
They reuse `AnsibleRunnerCiscoAdapter`, the existing
[`apply_interface_description.yml`](../../ansible/apply_interface_description.yml)
and its `cisco.ios.ios_config` task. The Cisco writer checks exact operation
admission before lifecycle-family compatibility, without device-name dispatch
or a second profile-ID allowlist.

Established merged validation evidence:

| Validation | Result |
|---|---|
| Focused merged matrix | 503 passed |
| Full local pytest | 2,731 passed / 3 skipped |
| Docker quality | 2,689 passed / 45 skipped |
| Exact Ansible runtime, lint/format, package, Terraform, Buildkite parser, Markdown and ledger/static checks | Passed |

Offline/temp tests establish planning and COMPLIANT behavior, protected-interface
and stale target/interface/profile/NOS/endpoint rejection, runtime prerequisite
failure, one-shot success, known failure and ambiguous execution without retry.
Independent POST determines outcome rather than provider `changed=True/False/None`.
Only eligible known-success/valid-POST mismatch permits the frozen inverse;
fresh recovery observation must match hostname, interface and prior description.
Wrong recovery facts cannot establish RECOVERED. Evidence failures never replay
the device command.

Both newly admitted profiles use the same intent → plan → promotion →
authorization functions, simulated execution, durable EXECUTION and COMPLIANCE
envelopes, exact artifact-byte verification, temporary AuditStore readback,
chronology child/receipt and final evidence. Chronology maps devices 8/9 to
`netbox-device-8`/`netbox-device-9` and retains `causality = NOT_PROVEN`.
COMPLIANCE requires no plan, promotion, authorization, execution or chronology.
These are offline lifecycle proofs, not LIVE execution claims.

No serialized schema changed:

| Contract | Retained version |
|---|---|
| `ProfiledOperationAdmission` | v1 |
| `ProfiledDeploymentPlan` | v2 |
| `ProfiledComplianceRecord` | v2 |
| `ProfiledPromotion` | v2 |
| `ProfiledChangeRecord` | v2 |
| `ProfiledDeliveryAuditRecord` | v1 |
| Current chronology | v1 |

Historical core/Junos artifacts, schemas, bytes and digests remain unchanged.
Historical acceptance documents retain the admission boundaries at their own
milestones; they were not rewritten.

## Real local planning evidence

Both targets traversed the normal local `ncdp profiled-plan` path:

```text
NetBox → personal AppRole → exact OpenBao credential
→ LIVE read-only device collection → schema-v2 planning
```

| Fact | Device 8 | Device 9 |
|---|---|---|
| Target / observed hostname | `transit-ios-01` | `access-sw-01` |
| Stable device | `netbox:dcim.device:8` | `netbox:dcim.device:9` |
| Automation profile | `iosv_159_3_m12` | `iosvl2_2020` |
| NOS | IOS | IOS |
| LIVE endpoint | `192.168.4.16:22` | `192.168.4.17:22` |
| Observed interface | `GigabitEthernet0/1` | `GigabitEthernet0/1` |
| Stable interface | `netbox:dcim.interface:14` | `netbox:dcim.interface:18` |
| Credential reference | `openbao:kv-v2:ncdp/devices/8/ssh` | `openbao:kv-v2:ncdp/devices/9/ssh` |
| Typed planning result | PLAN, schema v2 | PLAN, schema v2 |

Device-8 plan digest:

`sha256:b53ed3ab0eadbbf2940c041c1ebc0c0beb955c275c10e8c7c59e0f395773404e`

Device-9 plan digest:

`sha256:dbd300287a44bfc21050e0643b297913e72cc0b55a4e030dd54165e80c87a3b6`

Both real AppRole authentications, exact credential reads and read-only device
collections succeeded. Typed plan validation confirmed exact target/interface
binding, Cisco forward artifacts, frozen inverses and `cisco_targeted_inverse`.
No plan was deployed; temporary local intents did not alter the committed main
intent and disposable planning files were removed afterward.

For both IOS devices, `GigabitEthernet0/0` remained inventory-protected.
Production planning rejected it before secret reference, credential load or
device collection. Reuse did not bypass interface protection.

Existing LIVE trust validated. The installed exact runtime validated
`ansible.netcommon == 8.6.0` and `cisco.ios == 11.4.2` through the effective
collection path. No installation, upgrade or trust re-enrollment occurred.

## Bounded personal session and protected credential boundary

The existing `ncdp-personal-lab` role/policy matched exact device reads
**1 / 2 / 8 / 9**, with SecretID TTL **1,800 seconds**, **10 uses**, issued-token
TTL/max **300 seconds**, and **one token use**. Role and policy were unchanged.

Exactly one fresh bounded personal SecretID was explicitly authorized and issued
for the final proof, held in memory, used for both read-only planning passes,
then destroyed by its accessor. Subsequent non-consuming lookup confirmed its
absence. No credential values were included in evidence, and no unrelated
credential was replaced or rotated.

The dedicated `ncdp-buildkite-profiled-deploy` identity still has
`DEVICE_IDS = (1, 2)` in
[`openbao_profiled_deploy_config.py`](../../src/network_change_delivery/openbao_profiled_deploy_config.py).
Devices 8/9 were not added to this role. Its persistent SecretID and bounded
300-second, one-use token contract remain unchanged.

IOSv/IOSvL2 operation admission is distinct from protected Buildkite credential
permission. The absent protected device-8/9 permission is not a remaining
CAP-PROFILE-REUSE-WRITE implementation defect. The final read-only audit traced
the dedicated scope to PR #138: it is a historical/incremental authority
boundary, not a technical requirement to retain devices 1/2 forever. Any future
expansion requires separately approved roadmap scope; no expansion or rollout
scope amendment is part of this acceptance.

## Build 443: separate results, no CML acceptance claim

| Correlation | Value |
|---|---|
| Build | [443](https://buildkite.com/atheer-kareem/network-change-delivery-platform/builds/443) |
| Build UUID | `01a08211-7821-4f45-845a-bb16882038e1` |
| Main commit | `2bdfd1a82add97ff74cf21426519c5c9ff9588f2` |

Engineering validation and Batfish passed. Real disposable CML staging
**FAILED at service readiness**: `transit-ios-01` timed out after approximately
180.5 seconds, readiness was **3/4**, and read-only validation was **0/4**.
The job exited **2** and was soft-failed. No `profiled-cml-success` receipt was
published. Cleanup/destruction, independent absence verification and Terraform
state retirement succeeded.

Aggregate passed/blocked presentation is not CML success. Build 443 does not
establish CML acceptance. This failure does not invalidate profile-reuse
acceptance: the capability concerns explicit operation/profile admission and
reuse, with its required runtime proof independently obtained through controlled
real local planning. CML remediation is separate follow-up work.

Build 443 planning independently produced typed **COMPLIANT** for the unchanged
committed `core-02 / GigabitEthernet2` intent. Compliance digest:

`sha256:a1123cfd5f36e50b4b8a60f67214fdfcf9caf148fa4b48254dc2eed2e3d9b8ce`

Exact planning JSON-byte digest:

`sha256:0e842a0e3441ef67f2338bad9c81599df0b7899ddc798b4891f913b7b255751c`

Promotion/decision was **COMPLIANT / no promotion**. Human continuation was
never granted; deployment invocation count and device configuration writes were
**ZERO**. COMPLIANT established neither CML success nor deployment authority.

## Preservation and remaining boundaries

During the final controlled local proof:

- Device-8 and device-9 configuration writes: **ZERO**.
- Profiled deployment invocations, promotions and authorizations: **ZERO**.
- Buildkite, persistent CML and NetBox mutations: **ZERO**.
- Device credential rotations and protected Buildkite credential changes: **ZERO**.
- Real AuditStore: **11 historical / 1 profiled / 0 chronology**, unchanged.
- All **62 checked AuditStore file hashes** remained unchanged.
- The [committed main intent](../../deployments/live/profiled-demo.yaml) remained
  `core-02 / GigabitEthernet2 / managed-by-ncdp-profiled-demo`.

The authorized personal SecretID issuance/retirement and ordinary authentication
were the bounded credential actions; no acceptance evidence was fabricated.

The final diagnostic separately found unhealthy management-observability
realization: intended all-four probes absent, expired admission, empty discovery,
no readiness marker and last service exit 2. This is a current operational issue
for separate follow-up, not a change to profile-reuse acceptance. Neither
observability nor CML remediation is included in this closeout.

CAP-PROFILED-ROLLOUT remains **USER APPROVED**, with its scope unchanged;
CAP-OP-ASSURANCE remains **DEFERRED**. The temporary PR/development CML exception
remains **ACTIVE**. Batfish remains the B4 D1 prerequisite, not exact
description-candidate validation; CML remains realization/read-only integration
assurance, not rehearsal of the selected write. No rollout, broader protected
credential scope or unrelated write operation was accepted here.
