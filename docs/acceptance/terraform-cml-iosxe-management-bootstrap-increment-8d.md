# Terraform CML IOS XE management bootstrap — Increment 8D

## Accepted scope

Increment 8D-2 accepts persistent one-time manual management bootstrap and
read-only NCDP compatibility for the Terraform-created IOS XE `core-02`. The
proof used protected `main` commit
`597d5f3a584e12c1e86b3902339930de21f4dee4`, CML lab `NCDP Terraform Twin`
(`1a00ab4d-e44f-4a80-a8da-c73a329d6878`), and node
`44c3b115-68fb-474b-b30c-d291ad0af55c` with image
`cat8000v-17-18-02`.

The operator used the accepted CML browser-console channel to persist only the
management bootstrap: hostname `core-02`, `192.168.4.14/24` on protected
`GigabitEthernet1`, the existing OpenBao-backed privilege-15 local account, SSH
v2, NETCONF/YANG, and required non-sensitive domain/RSA settings. The operator
saved this bootstrap. `GigabitEthernet2` and its managed description intent were
not changed.

## Legacy isolation and stable identity

The accepted legacy lab `Lab at Wed 21:44 PM`
(`09605569-0468-4fc4-8684-beb5a1342b9c`) had returned to `STARTED` outside the
first attempt and reclaimed `192.168.4.14`. The resumed acceptance deliberately
stopped its five exact nodes. They transitioned from BOOTED to STOPPED and
remained STOPPED across repeated checks:

| Node | UUID | Before | Final |
| --- | --- | --- | --- |
| `ext-conn-0` | `9155d0a4-e72b-4ab9-9f62-8d485de3ace0` | BOOTED | STOPPED |
| `unmanaged-switch-0` | `e4542ca6-6fa9-46c6-bc95-6b437a8f270a` | BOOTED | STOPPED |
| `cat8000v-0` | `8c193771-d96a-4b0c-b8d6-9ce68333079b` | BOOTED | STOPPED |
| `vjunos-router-0` | `2644ab1e-cd24-4590-a165-8514681b2417` | BOOTED | STOPPED |
| `cat8000v-1` | `ff1e83b9-35b5-436e-ba16-320146c297fa` | BOOTED | STOPPED |

After isolation, `192.168.4.14` had no ICMP, TCP/22, or TCP/830 response. No
legacy configuration, stored configuration, topology, or link was changed, and
the legacy lab was not restarted. It remains stopped pending a later retirement
decision.

The existing NetBox identity was neither duplicated nor rewritten. Read-only
resolution returned `core-02`, `netbox:dcim.device:1`, platform `cisco_iosxe`,
endpoint `192.168.4.14:22`, protected `GigabitEthernet1`, and unprotected
`GigabitEthernet2` as `netbox:dcim.interface:2`.

## Credential and host-trust boundary

The existing `ncdp-personal-lab` AppRole contract remained unchanged. A fresh
bounded SecretID was used only in memory with its existing 1,800-second TTL and
10-use limit; issued tokens retained a 300-second TTL and one use. The existing
credential was read through `OpenBaoSecretProvider` at the unchanged reference
`openbao:kv-v2:ncdp/devices/1/ssh`. No role, policy, KV path, or device
credential changed, and no credential value entered logs, Git, evidence, or PR
content.

The stable endpoint's host key correctly changed with its CML realization. The
old RSA fingerprint was
`SHA256:KfhP5SKTnPbimZCFenRRokC7LRtGOKEIAgNbKB4uqoU`; the new Terraform
realization presented
`SHA256:2ecn6aaFjg730qXmwqczoWUHZ2D4kJWuVoaSLQJsTKc`. Only the
`192.168.4.14` known-host entry was replaced. Global host-key checking remained
enabled, and NCDP accepted the new fingerprint before authentication.

## Management and NCDP read-only result

Only `system-bridge`, `management-switch`, `core-02`, and their two Gi1
management-path links were started. The two other twin routers and all
data-plane links remained stopped. Direct reachability then found ICMP, TCP/22,
and TCP/830 available while legacy `cat8000v-0` remained stopped.

The existing NetBox/OpenBao/Ansible production path authenticated over SSH and
observed:

- hostname `core-02` and IOS XE `17.18.02`;
- protected, enabled `GigabitEthernet1` with `192.168.4.14/24`;
- unprotected `GigabitEthernet2`, disabled, with no IPv4 address or description;
  and
- credential source `openbao` and reference
  `openbao:kv-v2:ncdp/devices/1/ssh`.

`ncdp plan --netbox --openbao` completed fresh read-only collection, identity,
platform, interface-safety, and planning checks for `GigabitEthernet2`. It
produced a deployable interface-description plan because Gi2 was blank. The
safe plan metadata was inspected and its ignored temporary file removed. No
deploy command, execution adapter write, interface-description change, startup
save by NCDP, NetBox write, or OpenBao role, policy, KV, or device-credential
write occurred. The separately authorized bounded SecretID issuance was the only
OpenBao auth-backend mutation.

TCP/830 was reachable before and after restart, proving that NETCONF/YANG was
enabled and persisted. The already-installed `ncclient` could not complete a
server-hello because its current Paramiko transport rejected the IOS XE
`ssh-rsa` host-key type. No replacement client was installed, so this acceptance
does not claim an application-layer NETCONF session.

## State secrecy, persistence, and final invariant

While the saved bootstrap was active, direct CML inspection still found
zero-length `iosxe_config.txt` content. Terraform state retained empty router
`configuration` values and no non-empty `configurations`. The unsaved STOPPED
refresh plan showed 0 add, 1 change, and 0 destroy; only
`cml2_lifecycle.twin` proposed running-lifecycle reconciliation. No node
configuration update or replacement appeared, and the plan was not applied.
Terraform configuration remained empty after refresh.

With the management infrastructure still running, only the same Terraform
`core-02` was stopped and restarted. Without console reconfiguration, TCP/22
and TCP/830 returned. OpenBao-backed read-only SSH collection again observed
hostname `core-02`, IOS XE `17.18.02`, Gi1 `192.168.4.14/24`, and unchanged
blank Gi2. The saved bootstrap therefore persisted on the router disk while
remaining outside CML stored configuration and Terraform state.

Final cleanup stopped the Terraform management slice. All five twin nodes and
all six twin links were STOPPED, all five legacy nodes remained intentionally
STOPPED, raw CML router configuration remained empty, Terraform router
configuration remained empty, and the final Terraform STOPPED plan was 0 add,
0 change, and 0 destroy.

## Interpretation and remaining work

Increment 8 remains in progress. IOS XE manual persistent management bootstrap,
stable NetBox identity compatibility, existing OpenBao credential reuse, strict
SSH host-trust replacement, read-only NCDP planning, state secrecy, and restart
persistence are accepted. Junos bootstrap, reset/recreate acceptance, full
fleet cutover, and legacy retirement remain pending. This acceptance authorizes
no NCDP device deployment or write.
