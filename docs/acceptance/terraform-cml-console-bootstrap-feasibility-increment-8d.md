# Terraform CML console bootstrap feasibility — Increment 8D

## Accepted scope

Increment 8D-1 accepts the CML browser console as the one-time manual IOS XE
runtime-bootstrap channel for the personal digital twin. The proof used only
`core-02` (`44c3b115-68fb-474b-b30c-d291ad0af55c`) in the Terraform-owned
`NCDP Terraform Twin` lab (`1a00ab4d-e44f-4a80-a8da-c73a329d6878`) from exact
`main` commit `017e370e4b458e6b057cc1b05189db8323939b85`.

The operator used the normal CML browser console. At the optional IOS initial
configuration dialog the operator answered `no`, terminated autoinstall when
required, reached normal EXEC, entered privileged EXEC without an unknown
password, and successfully ran `show version`. The only runtime change was the
non-secret marker `hostname ncdp-8d1-console-probe`. The operator verified it in
running configuration and issued no save, write-memory, or running-to-startup
copy command.

Console-keystroke automation is intentionally abandoned. It adds little value
to the end-to-end NCDP demonstration compared with a bounded one-time manual
bootstrap followed by automated management-plane operation. This decision does
not move network configuration into Terraform: Terraform continues to own CML
infrastructure and lifecycle only.

## Baseline and isolation

`HEAD` and `origin/main` were the exact accepted commit and the worktree was
clean. Terraform `1.15.8` with exactly `CiscoDevNet/cml2` `0.9.3-beta1` produced
a STOPPED plan with 0 add, 0 change, and 0 destroy. The external state directory
and state file retained modes `0700` and `0600`.

All ten nodes across the two visible personal CML labs were observed STOPPED at
baseline. That observation replaced any older legacy-lab runtime assumption.
Only the exact Terraform-owned `core-02` node was started or stopped. The other
nine nodes remained STOPPED throughout; no unrelated legacy node was started or
restored.

Before start, direct CML inspection found the target `iosxe_config.txt` content
at zero length. Terraform state held `configuration = ""`, no non-empty
`configurations` content, and no marker text.

## Runtime state-secrecy proof

After CML reported `core-02` BOOTED, the operator applied and verified the
runtime hostname through the browser console. While that marker was active:

- direct CML inspection still found zero-length `iosxe_config.txt` content and
  no marker;
- Terraform state still held an empty `configuration`, no non-empty
  `configurations`, and no marker;
- the required unsaved STOPPED refresh plan showed 0 add, 1 change, and 0
  destroy; and
- `cml2_lifecycle.twin` was the only managed resource with a proposed action,
  reconciling the out-of-band running node toward STOPPED.

The plan was not applied. After its refresh, Terraform configuration remained
empty and contained no marker. Active IOS running configuration therefore did
not populate CML stored/day-zero configuration and was not imported into
Terraform state.

## Restart and final invariant

After the operator disconnected, only `core-02` was stopped without saving,
started again, and allowed to reach BOOTED. The operator re-entered through the
CML browser console and confirmed that
`show running-config | include ^hostname` did not contain
`ncdp-8d1-console-probe`. No new configuration was applied.

Only `core-02` was then stopped. Final direct inspection found all ten observed
nodes STOPPED, exactly matching baseline; target stored configuration remained
zero length. All three Terraform router resources retained empty
`configuration` values, no non-empty `configurations`, and no marker. The final
Terraform STOPPED plan was 0 add, 0 change, and 0 destroy.

## Interpretation and remaining work

This acceptance proves that manual CML console interaction is a viable
state-free runtime channel for one-time personal-twin IOS XE bootstrap, that
runtime IOS configuration stays outside CML stored configuration and Terraform
state, and that unsaved configuration disappears after restart.

Increment 8 remains in progress. This proof does not establish management-IP or
authentication bootstrap, SSH or NETCONF operation, Junos bootstrap,
reset/recreate acceptance, or NCDP cutover. The next step is the actual
management and authentication bootstrap sufficient for NCDP, followed by the
remaining reset/recreate and compatibility work.
