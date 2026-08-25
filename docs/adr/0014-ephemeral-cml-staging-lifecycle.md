# ADR 0014: Ephemeral CML staging lifecycle

## Status

Accepted. ADR 0012's authority boundaries and ADR 0013's personal-lab Day-0
boundary remain valid. This ADR supersedes the persistent operational staging
lifecycle assumed by the earlier Increment 8 work.

## Context

Increment 8 proved deterministic replacement of the complete 13-resource
Terraform-owned CML twin and clean Terraform convergence. Fresh first boots of
both IOS XE and vJunos became manageable automatically through their exact
Git-reviewed Day-0 renders, unchanged NetBox identities, and existing OpenBao
credentials. The accepted fresh vJunos realization required no console access
or device write.

The same vJunos UUID did not regain management connectivity after a later CML
restart. CML reported the node `BOOTED`, but ARP, ICMP, SSH, and NETCONF stayed
unavailable throughout the bounded readiness window. This issue was not fixed.
It exposed a mismatch between the persistent-lab acceptance contract and the
integration environment the delivery workflow actually needs.

## Decision

CML staging environments are disposable integration infrastructure. The normal
staging lifecycle is:

```text
absent -> fresh create -> first boot -> readiness -> validation/test
       -> sanitized evidence -> destroy -> absent
```

Each staging run creates a fresh Terraform-owned twin and validates devices
against fresh first-boot realizations. Complete Terraform destruction is
attempted after both success and failure. Build/run-scoped Terraform state is
retained when destruction fails, so cleanup can be diagnosed and resumed
without state removal or manual CML deletion. State is retired only after
successful destruction and independent CML absence verification.

Normal pipeline operation does not require same-realization restart
persistence. Reboot and restart behavior remains testable only as an explicit
scenario with its own acceptance contract; it is not a staging-infrastructure
readiness requirement.

CML UUIDs remain disposable realization identifiers. NetBox remains authority
for stable device/interface identity, address, platform, role, and targeting
metadata. OpenBao remains credential authority. Git/NCDP remains authority for
network intent, planning, validation, approval, execution, evidence, and
recovery. ADR 0013 continues to permit only the minimum personal-lab Day-0
manageability configuration in Terraform/CML.

The current fixed management addresses require serialized CML staging runs.
Parallel ephemeral twins require a future isolated management-network design;
duplicate fixed-address realizations are not accepted.

## Consequences

Increment 8 closes on reproducible fresh creation, first-boot manageability,
validation evidence, and complete destruction rather than persistent restart
acceptance. The current Terraform root and its `prevent_destroy` guard remain
unchanged after live cleanup. Increment 8E will design the reusable ephemeral
root/module and Buildkite lifecycle, including run identity, serialized
concurrency, finally-style destruction, cleanup proof, and failed-destroy state
retention.

The observed vJunos restart limitation remains recorded evidence. This decision
does not claim that it was corrected, and explicit reboot scenarios may still
investigate it independently.
