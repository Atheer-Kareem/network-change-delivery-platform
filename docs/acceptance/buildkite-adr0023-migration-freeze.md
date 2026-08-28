# Phase B2-G: Buildkite ADR 0023 migration execution guard

Status: external staging-agent freeze and repository guard complete; repository
evidence pending review.

## Authority and reason

Merged main `99e8620b15c0e837460469c297ece94549d75627`, validated by
natural Buildkite Build #185, is the starting authority. ADR 0023 Phase B2 moved
standing OpenBao staging credentials, policies, and JWT roles from live NetBox
devices 1/2 to staging devices 6/7 and retired the historical staging roles and
policies. The checked-in consumer still selects 1/2. It is therefore
intentionally fail-closed and must not execute during B3/B4 development.

The guard uses two independent boundaries: a checkout-independent macOS
LaunchAgent freeze and explicit false conditions on both legacy staging and
protected delivery in the repository pipeline.

## Installed staging-agent discovery

The sole installed personal-lab staging agent was:

| Property | Observed value |
| --- | --- |
| LaunchAgent | `com.buildkite.ncdp-staging` |
| Plist | `/Users/netdevops/Library/LaunchAgents/com.buildkite.ncdp-staging.plist` |
| Pre-freeze state | loaded and running; PID 763 |
| Executable | `/opt/homebrew/bin/buildkite-agent` 3.137.0 |
| Launcher | `/Users/netdevops/.config/buildkite/ncdp-lab/bin/start-ncdp-staging` |
| Agent config | `/Users/netdevops/.config/buildkite/ncdp-lab/agents/ncdp-staging.cfg` |
| Queue | `ncdp-staging` |
| Agent zone tag | `ncdp-zone=staging` |
| Hook directory | `/Users/netdevops/.config/buildkite/ncdp-lab/hooks/ncdp-staging` |
| Command hook | `<hook-directory>/command` |
| Protected hook environment | `<hook-directory>/staging.env`; mode `0700` |
| Launcher environment | `/Users/netdevops/.config/buildkite/ncdp-lab/env/ncdp-staging.env`; mode `0600` |
| State root | `/Users/netdevops/.local/state/ncdp/terraform/cml/buildkite-staging`; mode `0700` |

The plist, launcher, config, hooks, environments, credentials, and state root
were preserved. Their contents were not placed in evidence.

Local launchd configuration and process inspection found one staging queue
agent alongside distinct validation and deployment agents. The agent
registration token did not carry organization agent-list authority (the
read-only API request returned HTTP 401), so organization-wide enumeration was
not available from this host. No other staging-capable agent is present in the
installed personal-lab authority or known project operating model.

## Hook provenance and clean lifecycle

The merged-main hook and installed agent-owned hook both had SHA-256:

`24b3951609df5c98ed5cc602d5ab844e6d1c2901645b32d7bac479c658f3b562`

The installed hook was an owner-managed, non-symlink regular file with mode
`0700`. The repository source was a regular file with mode `0755`. Equality was
exact; no hook overwrite was required.

The agent had no child job process. Recent logs showed its last staging job had
completed, and no current `cml-staging` execution existed. The staging root had
no Terraform state, run evidence, or other retained file requiring recovery.
It contained only one empty historical run directory with an empty
`terraform-data` directory; the increment preserved it rather than deleting
operational state.

## External hard freeze

At `2026-08-28T08:06:19Z`, the operator used the discovered user launchd domain
to disable and boot out only `gui/501/com.buildkite.ncdp-staging`. The first
immediate observation caught asynchronous shutdown in progress; the next
bounded poll proved:

- `com.buildkite.ncdp-staging` explicitly disabled;
- LaunchAgent absent from the loaded service domain;
- staging agent process absent;
- validation and deployment agents still running.

No protected file, agent token, credential, hook, environment, state root, or
plist was deleted or rewritten. The `ncdp-staging` agent must remain disabled
until a separately reviewed B4 cutover explicitly authorizes the migrated
protected consumer. Re-enable requires B4 review, migrated consumer acceptance,
and removal of both repository freeze conditions; this increment does not
authorize it.

## Repository pipeline freeze

The retained `cml-staging` definition now has an unconditional Buildkite
expression:

```yaml
if: "false"
```

The protected-delivery group independently retains its historical main-only
guard behind an explicit false prefix:

```yaml
if: false && build.branch == "main" && build.pull_request.id == null
```

Quality and pipeline-contract validation remain unconditional. Tests require
both exact conditions, preventing an incidental pipeline edit from silently
removing either guard. The external LaunchAgent freeze remains effective even
if checkout-controlled pipeline content is defective.

The migration lifecycle is:

```text
B2 complete
-> external staging agent frozen
-> pipeline staging and protected delivery frozen
-> B3/B4 development allowed after merge-main guard proof
-> migrated controller and consumer reviewed
-> separate B4 cutover authorization
-> external staging agent re-enabled
-> migrated staging execution accepted
```

This increment did not begin B3/B4 or run staging. Increment 11A remains paused
for ADR 0023 migration, and 11B has not started.
