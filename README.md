# PadDock
<p align="center">
  <img src="logo/img.png" alt="PadDock logo" width="200">
</p>

Tested, least-privilege bundles for running AI coding agents inside
[NVIDIA OpenShell](https://github.com/NVIDIA/OpenShell) sandboxes.

**Status:** early development. Not ready for use yet.

PadDock is an independent community project. It is not affiliated with or
endorsed by NVIDIA.

## Bundles

| Agent | Bundle | Auth |
|---|---|---|
| OpenCode 2.0.21 | [bundles/opencode](bundles/opencode) | OpenRouter API key |

## What CI proves for every bundle

- **Must work:** the agent starts, writes its state, and reaches its model API.
  The sandbox sees only OpenShell's credential placeholder, never the key.
- **Must block** ([tests/deny/run.sh](tests/deny/run.sh)), from a process outside
  the agent and again from a probe given exactly the agent's rules:
  unlisted hosts, DNS of unlisted names, DNS to outside resolvers, TCP and UDP to
  IP addresses, IPv6, `sentry.io`, disallowed methods and paths on the allowed
  host, and writes outside the writable folders. A check passes only on
  OpenShell's own evidence ([ADR 0002](docs/decisions/0002-must-block-observations.md)).
- **Within bounds:** `openshell-prover` confirms the effective policy stays inside
  the bundle's `boundary.yaml`.

## Layout

- `bundles/<agent>/`: one bundle per agent (image reference, sandbox policy,
  boundary policy, provider profiles, tests).
- `scripts/paddock/`: Python helpers used by CI (`python -m paddock --help`).
- `scripts/ci/`: bash scripts that run bundles against real OpenShell gateways.
- `docs/`: design spec, plans, and decision records.

## License

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
