# CML managed-pair structural refactor — Phase B3-1

## Authority and scope

This non-executing increment starts from merged main
`409570b98a4849c4d32da17bdaa202dde14a2285` and natural merged-main Buildkite
Build #187 (`PASSED`). ADR 0023 and the B2-G migration guard remain controlling
authority.

Before the refactor, the protected staging state root contained no Terraform
state or retained realization requiring recovery. The
`com.buildkite.ncdp-staging` LaunchAgent was disabled and unloaded, pipeline
`cml-staging` remained `if: "false"`, and protected delivery remained explicitly
false. Those safeguards were not changed.

## Structural result

The historical `modules/twin` graph remains one lab, five nodes, six links, and
one lifecycle resource: thirteen resources. Phase B3-1 adds
`modules/managed-pair` and moves only the ephemeral root to it. The target graph
is one lab, four nodes, four links, and one lifecycle: exactly ten resources.
The nodes are System Bridge, management switch, Cisco, and Junos. The links are
bridge-management, management-Cisco, management-Junos, and Cisco-Junos.

The removed baseline elements are the `core-03` node,
management-to-core-03 link, and Junos-to-core-03 link. The new module also has
no core-03 lifecycle trigger, output, or unmanaged bootstrap. The direct
Cisco/Junos link is staging integration topology, not evidence of brownfield
live wiring.

Node labels and bootstrap inputs use Cisco/Junos topology roles rather than
canonical live names. Credential inputs remain sensitive and required; no
credential or address is committed.

## Migration boundary

The root and `modules/twin` remain frozen historical operator-twin code. They
are neither live/reference authority nor an authorized execution path.
Historical acceptance records were not rewritten.

Only the staging driver's structural node, link, output, and Terraform-address
contracts changed. Its NetBox and OpenBao selection still targets historical
devices 1/2 and `.14`/`.20`. B2 removed that staging credential authority, so
the checkout remains intentionally unusable and fail closed. B3-2 must add the
protected manifest/controller, independent devices 6/7 resolution, live
endpoint denial, and protected Terraform authority before execution.

No CML lab was created, readied, started, stopped, or destroyed. There was no
Terraform live plan, apply, or destroy; no CML, NetBox, OpenBao, Buildkite
runtime, or device mutation; and no staging or protected-delivery execution.
11A remains paused and 11B did not start.

## Validation

Focused static tests prove the exact ten-address Terraform graph, four-node and
four-link populations, lifecycle dependency/trigger population, module-local
bootstrap set, output set, core-03 absence, and unchanged migration-freeze
conditions. Both CML roots pass Terraform 1.15.8 backend-free initialization
and static validation with the locked `CiscoDevNet/cml2` `0.9.3-beta1`
provider. Host and Docker quality suites, Ruff, Ansible lint, package build, CLI
smoke, shell syntax, runtime-image smoke, sensitive-pattern review, and
`git diff --check` pass. No CML credential was supplied to validation.
