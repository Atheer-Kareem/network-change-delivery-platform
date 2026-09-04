# Profiled deploy LIVE acceptance — PR #132

## Scope and authority

This acceptance ran at reviewed PR #132 HEAD
`14b725b28724713ed939485f562879ac77d6deb7` on branch
`feat/detour-b-profiled-deploy-activation`. The worktree was clean before and
after the run. It exercised the local schema-v2 `ncdp profiled-deploy` surface
for exactly two approved interface-description operations: one C8000V IOS-XE
operation and one vJunos operation.

The execution path used the profiled NetBox/OpenBao boundaries and the accepted
profiled LIVE trust generation. Each device phase used one fresh bounded
personal-lab OpenBao AppRole SecretID, which was retired after its plan, one
deployment attempt, and independent read-only verification. Personal-lab
authority verification passed. No role, policy, mount, auth-method, or device
KV credential changed.

The private schema-v2 plans and `ProfiledChangeRecord` evidence remain local
acceptance artifacts; no credential material or private evidence JSON is
committed here.

## Cisco C8000V IOS-XE

The approved target was `core-02` / `netbox:dcim.device:1`, interface
`GigabitEthernet2` / `netbox:dcim.interface:2`, at `192.168.4.14:22`. The
profile was `cat8000v_iosxe`; the OpenBao reference was
`openbao:kv-v2:ncdp/devices/1/ssh`.

The immutable schema-v2 plan bound prior description `null` and desired
description `ncdp-pr132-live-core-14b725b`, with transaction strategy
`cisco_targeted_inverse` and digest
`sha256:eda4fa5cbec3c02feb9d6ea0770c76d8228220a4ed7404faa923ce61cf67a918`.

Exactly one primary write was attempted. Fresh preflight, execution, and
independent post-write validation all succeeded; post-validation observed the
exact desired description. The final outcome was `SUCCEEDED`. Recovery was not
attempted, and `managed_state_acceptance_attempted` remained `false`.

A fresh read-only profiled plan with the same intent then reported the target
already compliant and produced no verification plan artifact. No second write
was attempted.

## vJunos

The approved target was `edge-junos-01` / `netbox:dcim.device:2`, interface
`ge-0/0/2` / `netbox:dcim.interface:8`, at `192.168.4.20:830`. The profile was
`vjunos_router`; the OpenBao reference was
`openbao:kv-v2:ncdp/devices/2/ssh`.

The immutable schema-v2 plan bound prior description `null` and desired
description `ncdp-pr132-live-junos-14b725b`, with transaction strategy
`junos_commit_confirmed`, confirmed timeout five minutes, confirmation operation
`confirm_previous_commit`, and digest
`sha256:b0a688412dedb4dfee86b2b516ee6f9fa645a90d017fb942e1bc516b8befd5c3`.

Exactly one primary write was attempted. Candidate validation succeeded and
captured candidate-diff digest
`sha256:721de8abe0552c24c6ba281bf7b65dd0431acb52c508fc3211ee451af042b0e1`.
The single commit-confirmed attempt, independent post-write observation, and
explicit confirmation all succeeded. Post-validation observed the exact desired
description. The final outcome was `SUCCEEDED`. Recovery was not attempted, and
`managed_state_acceptance_attempted` remained `false`.

A fresh read-only profiled plan with the same intent then reported the target
already compliant and produced no verification plan artifact. No second write
was attempted.

## B5 and external authority boundary

The B5 managed-state store was byte-for-byte identical before and after the
acceptance: the same four generation-one `INITIAL_ADOPTION` records remained,
with no generation two, `POST_WRITE_VALIDATED`, or D0 advancement. Interface
description is outside the current B5 managed envelopes, so this acceptance did
not attempt managed-state acceptance.

There was no NetBox mutation, CML mutation, device 8/9 access, staging or
protected-delivery activation, or Buildkite inspection. The total intended
primary device-write count was exactly two.

## Limits of this acceptance

This evidence accepts only the two profiled interface-description operations
described above. It does not prove profiled write authority for IOSv, IOSvL2,
routed underlay, OSPF, VLAN/trunk, ACL, SNMP, fleet rollout, or protected
delivery.
