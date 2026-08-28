# ADR 0013: Personal-CML Day-0 bootstrap boundary

## Status

Accepted for Increment 8D-2B. This decision supersedes only ADR 0012's
prohibition on credential-bearing Terraform/CML Day-0 configuration inside the
personal CML digital twin. ADR 0014 retains this boundary for fresh ephemeral
staging realizations; it changes their lifecycle, not their authority or Day-0
scope.

ADR 0023 scopes this Terraform credential-bearing Day-0 exception to staging
and explicit scenarios after migration. Brownfield live uses a separately
reviewed manual minimum-bootstrap boundary; Terraform has no live authority.

## Context

Increment 8D-2 proved a one-time manual IOS XE management bootstrap, unchanged
NetBox identity and OpenBao credential reuse, strict SSH trust, read-only NCDP
planning, and restart persistence. That boundary kept the saved device bootstrap
outside Terraform state and CML stored configuration, but it could not make a
new or replaced router manageable without browser-console work.

The personal digital twin now needs deterministic create/recreate behavior. The
pinned CML2 provider treats `cml2_node.configuration` as Day-0 configuration and
replaces a previously started node when this value changes. CML stores the
rendered payload and Terraform stores it in external state. Terraform sensitivity
marking redacts normal display but does not encrypt or remove state content.

## Decision

For the personal CML digital twin only, Terraform/CML may own the minimum Day-0
initialization required to make a lab router manageable: hostname realization,
management interface and address, a local lab management account, SSH and
NETCONF prerequisites, and minimum platform initialization. This is
infrastructure initialization, not NCDP-managed network intent.

NetBox remains authoritative for stable device and interface identity,
management address, platform, role, and targeting/protection metadata. OpenBao
remains authoritative for the device credential even though a credential copy
is deliberately materialized into Terraform external state and CML Day-0
storage. Git/NCDP remains authoritative for managed network intent, including
interface descriptions, validation, planning, approval, deployment, and
recovery. Day-0 must not include that managed intent.

Runtime values must be read freshly from NetBox and OpenBao and passed as
required sensitive Terraform inputs. Credentials have no defaults and no
credential-bearing `.tfvars` file may be created. The rendered configuration is
marked sensitive so ordinary Terraform output does not display it. No actual
credential may enter Git, PR content, Buildkite logs, acceptance evidence, or
normal CLI output.

External Terraform state remains outside Git with restrictive permissions on
encrypted host storage. Because the state and CML payload intentionally contain
the credential copy, access to both is privileged. Saved Terraform plans that
contain the bootstrap are prohibited.

This exception is not accepted for production and does not establish a
production secret-distribution design.

## Consequences

A controlled node replacement can install the IOS XE management bootstrap on
first boot without manual console configuration. Changing the bootstrap after a
node has run replaces that CML realization; the existing node ID and generation
lifecycle triggers reconcile the replacement graph.

The accepted tradeoff is increased personal-lab secret exposure in Terraform
state and CML storage. Restrictive storage, bounded secret retrieval, sensitive
display handling, narrow Day-0 scope, and prohibition of saved plans reduce but
do not eliminate that risk. Credential rotation requires replacement of the
affected lab node and renewed SSH host trust.
