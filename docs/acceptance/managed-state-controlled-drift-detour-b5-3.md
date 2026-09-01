# Detour B5-3 controlled drift and recovery acceptance

Date: 2026-09-02

B5-3 proves the read-only managed-state drift boundary against the persistent
four-device LIVE realization. The operator changed only the running
configuration of `transit-ios-01/GigabitEthernet0/1` in the CML console:
`no shutdown` introduced the drift and a later `shutdown` restored accepted
D0. No NCDP execution path was used.

## Persistent D0 integrity

The managed-state store was checked before and after the run. It is unchanged:

| Vertical | Record digest | Generation | Acceptance mode |
| --- | --- | ---: | --- |
| `routed_underlay` | `sha256:ec66865f6ff0b6586c6d5f8526e5ca37385a59bf0aac6950db484817e3b3461a` | 1 | `INITIAL_ADOPTION` |
| `ospf` | `sha256:34d575f68125efccd6cbfad23d1ef980289b6bdfdba7c567e14e5ed1921e6418` | 1 | `INITIAL_ADOPTION` |
| `vlan` | `sha256:0ede0553403a0f112a8a814c99ed0421a574d27f4cef1f3171baf67a905a439c` | 1 | `INITIAL_ADOPTION` |
| `acl` | `sha256:b4e2c0c780473669f58bb3cf3599b8b94183bc76940a40cbeffac3a9812f8cda` | 1 | `INITIAL_ADOPTION` |

There are exactly four record files total, no generation 2, no
`POST_WRITE_VALIDATED` evidence, and no `current.json`. These record digests,
generations, and modes were identical before and after verification.

## Secret-free verifier evidence

The verifier artifacts were captured outside the checkout with mode `0600`.
Their SHA-256 digests are:

| Phase | Artifact | SHA-256 |
| --- | --- | --- |
| Pre-drift | `ncdp-b5-3-pre-drift-verification.json` | `sha256:9c2a189fc7959931cd7748f6f35bc6cbe3a9787549d073dcccd07d243397bf2e` |
| Drift | `ncdp-b5-3-drift-verification.json` | `sha256:a25567aafcedff7c56c60c2e6b444733d740de3066926d32032197364a3079e0` |
| Recovery | `ncdp-b5-3-final-recovery-verification.json` | `sha256:9c2a189fc7959931cd7748f6f35bc6cbe3a9787549d073dcccd07d243397bf2e` |

The pre-drift and recovery payloads are byte-identical. No secret-bearing
payload was copied into evidence or this document.

## Outcomes and state sequence

| Phase | Exit | `routed_underlay` D0/O | Other D0/O outcomes | D0/D1 outcomes |
| --- | ---: | --- | --- | --- |
| Pre-drift | 0 | `IN_SYNC` | `ospf`, `vlan`, `acl`: `IN_SYNC` | all four `CHANGE_PROPOSED` |
| Drift | 2 | `DRIFT_DETECTED` | `ospf`, `vlan`, `acl`: `IN_SYNC` | all four `CHANGE_PROPOSED` |
| Recovery | 0 | `IN_SYNC` | `ospf`, `vlan`, `acl`: `IN_SYNC` | all four `CHANGE_PROPOSED` |

The exact routed-underlay canonical state sequence is:

```text
pre-drift O       = sha256:6951568295ee0d1c1ff118ce68fd1324ade2a241a3d85049c82c83eaa1543c40  (accepted D0)
drift O           = sha256:497d2b55e4e1783c11f9af1b4f103ff4ac818418dcd9fa378a5d2a65647cb084
recovered O       = sha256:6951568295ee0d1c1ff118ce68fd1324ade2a241a3d85049c82c83eaa1543c40  (accepted D0)
```

Write accounting is explicit: NCDP-authorized device writes were `0`; the
out-of-band operator made exactly two running-configuration transitions. The
first `no shutdown` introduced the managed admin-state drift, and the second
`shutdown` restored the accepted D0. The final LIVE state equals D0. The
persistent D0 store was not touched.

Detour B5-3 completes the managed-state controlled-drift demonstration without
adding execution, auto-heal, drift acceptance, or D0 advancement authority.
