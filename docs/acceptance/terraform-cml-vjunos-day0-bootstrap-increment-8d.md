# Terraform CML vJunos Day-0 investigation — Increment 8D

## Outcome

Persistent Increment 8D-3 restart acceptance **failed**. Fresh-first-boot
reproducibility **passed** and motivated the accepted ephemeral staging
lifecycle in [ADR 0014](../adr/0014-ephemeral-cml-staging-lifecycle.md). This
report does not reinterpret the failed persistent contract as a pass.

## Day-0 delivery diagnosis

Initial vJunos trials exposed a CML controller prerequisite: Configuration
Customizer Scripts had to be enabled and CML restarted. An isolated native
scratch lab then separated CML delivery from Junos configuration semantics.
The current Terraform template rendered an exact 740-byte configuration with
SHA-256
`9214f505cc26b987bfd1942638e12846aca95e7786e9bb7f484503467dd88762`.
Non-printing comparison proved exact equality with CML's stored
`config/juniper.conf`; the boot log contained neither the missing-configuration
error nor factory-configuration fallback.

The decisive scratch reproduction built the management links before wiping the
vJunos node, restored the exact render, and performed its first boot. ARP, ICMP,
TCP/22, TCP/830, non-root SSH, and non-root NETCONF all passed. Read-only checks
confirmed hostname `edge-junos-01` and `fxp0` at `192.168.4.20/24`. This proved
the template, customizer processing, slot-0/`fxp0` mapping, external management
fabric, and existing OpenBao account on a clean realization.

## Whole-twin recreation and fresh acceptance

An explicit replacement plan named all 13 managed resources because replacing
the lab alone caused provider `0.9.3-beta1` to plan child `lab_id` changes as
in-place updates. The accepted complete replacement was 13 add, 0 change, and
13 destroy: one lab, five nodes, six links, and the lifecycle resource. A fresh
plan then converged at 0 add, 0 change, and 0 destroy.

Fresh `core-02` first boot automatically provided `192.168.4.14`, ARP, ICMP,
SSH, TCP/830, hostname validation, and authentication with the existing OpenBao
credential. Fresh `edge-junos-01` realization
`c0228a0c-3dd3-4e95-b371-03efd8d8e27c` consumed the exact 740-byte render and
automatically provided ARP, ICMP, SSH, NETCONF, non-root authentication,
hostname validation, and `fxp0` `192.168.4.20/24`. Accepted fresh realizations
used zero console operations and zero device writes.

## Persistent restart failure

The accepted vJunos UUID was stopped and started without wipe, replacement,
configuration change, credential rotation, console access, or device write.
CML reported `BOOTED` after approximately 612 seconds. After a further bounded
900-second management-readiness window, ARP, ICMP, TCP/22, and TCP/830 all
remained unavailable. Authentication and NCDP compatibility could therefore
not be attempted. The same-realization restart problem was not fixed.

The old persistent 8D-3 contract was consequently not satisfied. The evidence
instead established that deterministic fresh-first-boot staging is reliable
and that persistent realization reuse is the wrong general staging contract.

## Final cleanup

The final Terraform-owned lab `13d78008-885c-4c5f-b5c7-ef46dd9ebbf7` was
destroyed through an exact safe plan and apply of 0 add, 0 change, and 13
destroy. All 13 delete operations completed. CML returned 404 for the lab, no
Terraform-owned `NCDP Terraform Twin` remained, and `terraform state list` was
empty. The external empty state was retained. The temporary `prevent_destroy`
maintenance edit was exactly reversed; `topology.tf` returned to SHA-256
`f7dbf93751b822e2ebe87293cc5c6811d9ab8a5fd52f863720dd3f0f496593df`.

During final Terraform destruction, the diagnostic scratch lab and legacy lab
remained untouched and fully stopped. NetBox was read only. OpenBao issued
bounded runtime credentials but its role, policy, KV data, and device
credentials were unchanged. No NCDP deploy, network-device configuration,
console operation on an accepted fresh realization, or device write occurred.
