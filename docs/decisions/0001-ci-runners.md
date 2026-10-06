# 0001: Run CI on GitHub's free hosted runners

- Status: accepted
- Date: 2026-10-06
- Run: https://github.com/paddockhq/paddock/actions/runs/37473794708

## Context

Spec §7.1 plans CI on free GitHub-hosted runners. OpenShell's own Docker-driver
tests run on larger runners, so it was unproven that free runners can run
OpenShell at all (spec Q4).

## Result

| Runner | OpenShell | Gateway connected | Sandbox Ready | Egress blocked | Denial logged |
|---|---|---|---|---|---|
| ubuntu-24.04 | v0.1.2 | yes | yes | yes | yes |
| ubuntu-24.04 | v0.0.116 | yes | no | n/a | n/a |
| ubuntu-24.04-arm | v0.1.2 | yes | yes | yes | yes |
| ubuntu-24.04-arm | v0.0.116 | yes | no | n/a | n/a |

Measured on the runners: kernel 6.17.0-1022-azure, LSM list
lockdown,capability,landlock,yama,apparmor,ima,evm, cgroup filesystem
cgroup2fs, Docker 28.0.4. All four values were the same on both runners.

The first run (37473500516) gave the same four outcomes. The second run added
`docker logs` to the failure diagnostics to find the v0.0.116 cause.

## Decision

Test only OpenShell v0.1.2 for now; v0.0.116 failed because its supervisor
creates the sandbox network namespace by running `/sbin/ip netns add` from the
sandbox image, and the Alpine test image only has BusyBox `ip`, which has no
`netns` command ("Network namespace creation failed and proxy mode requires
isolation ... /sbin/ip netns add sandbox-03f62fa9 failed: BusyBox v1.37.0").

## Notes

- The failure is a property of the image, not of the runner. On v0.0.116 a
  sandbox image needs iproute2. The upstream OpenCode image is Alpine without
  iproute2, so it would fail on v0.0.116 too. v0.1.2 has no such requirement.
- Images PadDock builds (Codex, Claude Code) can add iproute2. If they do,
  v0.0.116 can return to the matrix for those bundles through
  `openshell_min_version`.
- v0.1.2 logs two lines for a blocked request: a DNS refusal
  (`NET:REFUSE [MED] DENIED example.com [reason:policy_dns_ineligible]`) and the
  connection denial
  (`NET:OPEN [MED] DENIED /usr/bin/curl(0) -> example.com:443 [reason:transparent_tcp_policy_denied]`).
  M3's must-block tests can match either.
