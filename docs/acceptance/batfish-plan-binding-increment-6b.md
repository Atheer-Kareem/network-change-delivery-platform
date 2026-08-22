# Batfish plan binding — Increment 6B

This acceptance is wholly synthetic and offline. It binds a real validated
three-member `FleetDeploymentPlan`, a separately digested policy, frozen
baseline bytes, a candidate derived internally from that plan, and a bounded
Batfish result in one self-digested `PlanAssuranceRecord`.

The reference fleet plan targets `core-02`, `edge-junos-01`, and `core-03`.
The derived candidate changes exactly the three planned interface descriptions;
the unrelated Junos transit interface remains unchanged. Its candidate manifest
matches the committed plan-bound reference snapshot.

The explicit integration acceptance passed with exact file/node coverage, zero
initialization issues, a reachable critical flow in both snapshots, and zero
differential reachability changes. `verify-assurance` re-derived and verified
the record offline. Wrong plan, policy, or baseline inputs fail closed.

The generic 6A command remains provider-level diagnostic assurance and is not a
deployment authorization. 6B does not establish baseline freshness,
provenance, signer identity, protected-branch approval, or device state at
deployment time. Deployment integration is deferred to Increment 7.
