# Terraform CML lifecycle acceptance — Increment 8C

## Accepted scope

Increment 8C completed the first operational lifecycle acceptance of the
Terraform-owned `NCDP Terraform Twin` from protected `main` commit
`a087cab9fe45bf3c64d548cdfbe73e5f38b6fc93`. The run used Terraform `1.15.8`
and exactly `CiscoDevNet/cml2` `0.9.3-beta1`. It transitioned the existing twin
from `DEFINED_ON_CORE` to `STARTED`, accepted its runtime, and transitioned it
to the steady operational `STOPPED` state. It did not request
`DEFINED_ON_CORE` after start.

The accepted legacy lab was retained. Only its three verified heavy routers
were stopped temporarily for capacity and then restored. No topology mutation,
resource replacement, reset, wipe, destroy, import, bootstrap, configuration
generation, management cutover, NetBox access, OpenBao access, device
authentication, device command, or device configuration occurred.

## Source and safety gates

`origin/main`, local `main`, and `HEAD` were exactly the accepted source commit,
and the worktree was clean before operational acceptance. The required CML
token/TLS environment was present without logging values, prohibited CML and
Terraform override variables were absent, and the lifecycle input was absent
from the parent shell. The external state existed with mode `0600` under a mode
`0700` parent. Terraform initialized that backend with the exact locked
provider.

The baseline `DEFINED_ON_CORE` refresh plan was 0 add, 0 change, and 0 destroy.
State contained exactly 13 managed resources and lifecycle
`DEFINED_ON_CORE`. All three router `configuration` values were empty, no
`configurations` value had non-empty content, and direct CML inspection found
zero-length stored configuration for every router.

## Capacity and temporary legacy hold

The live controller was ready and healthy, its CML Personal license was in
compliance with 20-node capacity, and compute admission was `READY`.
Immediately before the hold, the controller had 10 defined nodes and 5 running
nodes. It reported 14 total CPUs, 6 allocated CPUs, 16,210,616,320 bytes free
RAM, and 911,333,654,528 bytes free disk.

The legacy lab `09605569-0468-4fc4-8684-beb5a1342b9c`, titled
`Lab at Wed 21:44 PM`, had this exact pre-mutation state:

| UUID | Label | State |
| --- | --- | --- |
| `9155d0a4-e72b-4ab9-9f62-8d485de3ace0` | `ext-conn-0` | `BOOTED` |
| `e4542ca6-6fa9-46c6-bc95-6b437a8f270a` | `unmanaged-switch-0` | `BOOTED` |
| `8c193771-d96a-4b0c-b8d6-9ce68333079b` | `cat8000v-0` | `BOOTED` |
| `2644ab1e-cd24-4590-a165-8514681b2417` | `vjunos-router-0` | `BOOTED` |
| `ff1e83b9-35b5-436e-ba16-320146c297fa` | `cat8000v-1` | `BOOTED` |

The three router UUID/label mappings were verified directly before mutation.
Only those routers were stopped, sequentially, and each reached `STOPPED`.
`ext-conn-0` and `unmanaged-switch-0` remained `BOOTED` and were never targeted.

After the hold, the controller reported 2 running nodes, 14 unallocated CPUs,
31,255,265,280 bytes free RAM, 911,333,515,264 bytes free disk, and compute
admission `READY`. Free RAM exceeded the required 19,327,352,832-byte threshold
by 11,927,912,448 bytes, preserving more than the required 4,096 MiB reserve
above the twin's 14,336 MiB request.

## STARTED acceptance

Both the unsaved speculative plan and independently generated interactive
apply-time plan showed exactly 0 add, 1 change, and 0 destroy. The only managed
resource updated was `cml2_lifecycle.twin`, from `DEFINED_ON_CORE` to `STARTED`.
The apply used an interactive `yes`; it did not use `-auto-approve`, piped
confirmation, or a saved plan. It completed successfully in 4 minutes 32
seconds with 0 added, 1 changed, and 0 destroyed.

Direct acceptance found the twin lab `STARTED`; `core-02`, `edge-junos-01`, and
`core-03` all `BOOTED`; `system-bridge` and `management-switch` both `BOOTED`;
and all six managed links `STARTED`. No router authentication or network-level
reachability, identity, routing, or forwarding claim was made. The STARTED
idempotency plan was 0 add, 0 change, and 0 destroy.

While the twin was running and the legacy heavy routers remained stopped, the
controller reported 7 running nodes, 6 allocated and 8 unallocated CPUs,
16,205,672,448 bytes free RAM, 910,867,300,352 bytes free disk, and compute
admission `READY`. This is observational runtime-cost evidence, not a future
admission guarantee.

## STOPPED acceptance

Both the unsaved speculative plan and independently generated interactive
apply-time plan showed exactly 0 add, 1 change, and 0 destroy. The only managed
resource updated was `cml2_lifecycle.twin`, from `STARTED` to `STOPPED`. The
apply again used an interactive `yes`, with no `-auto-approve`, piped
confirmation, or saved plan. It completed successfully with 0 added, 1 changed,
and 0 destroyed.

Direct acceptance found the twin lab, all three routers, both infrastructure
nodes, and all six links `STOPPED`. Both the immediate and final STOPPED
idempotency plans were 0 add, 0 change, and 0 destroy. No post-start
`DEFINED_ON_CORE` request, reset, or wipe occurred.

## State secrecy and final invariant

After STARTED and again after STOPPED, Terraform state retained empty router
`configuration` values and no non-empty `configurations` content. Direct CML
inspection found `iosxe_config.txt`, `config/juniper.conf`, and
`iosxe_config.txt` still zero length for `core-02`, `edge-junos-01`, and
`core-03`, respectively. Exact-byte scans found no persisted CML token or CA
PEM. No configuration content was printed.

Only after STOPPED acceptance, fresh capacity remained `READY` with
31,262,171,136 bytes free RAM, 910,866,927,616 bytes free disk, and 14
unallocated CPUs. The same three legacy routers were then started sequentially
by their verified UUIDs, and each reached `BOOTED` before the next was started.

The final invariant is:

- Terraform twin lab, all five twin nodes, and all six twin links: `STOPPED`.
- Legacy `ext-conn-0` and `unmanaged-switch-0`: `BOOTED` and never targeted.
- Legacy `cat8000v-0`, `vjunos-router-0`, and `cat8000v-1`: restored `BOOTED`.
- Final Terraform STOPPED plan: 0 add, 0 change, 0 destroy.
- Terraform and raw CML router configuration: empty.
- CML token persisted: no.

Increment 8D remains responsible for reset/recreate, state-free bootstrap,
management cutover, and NetBox/OpenBao/NCDP compatibility.
