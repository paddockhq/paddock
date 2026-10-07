# OpenCode bundle

Runs [OpenCode](https://github.com/anomalyco/opencode) 2.0.21 (MIT) inside an
OpenShell sandbox. The agent can reach only OpenRouter's chat completions API.

| | |
|---|---|
| Image | `ghcr.io/anomalyco/opencode:2.0.21@sha256:6d3cebbaaeed11b9dd1ea6d2ca8a3ec17eb548c5aed37e17c7ae80fd8b2f22b2` (official, pinned by digest) |
| Network | `openrouter.ai:443`, `POST /api/v1/chat/completions` only, for `/usr/local/bin/opencode` and the processes it starts |
| Writable | `/sandbox` (working folder and home), `/tmp` |
| Runs as | UID/GID 1000 |
| Auth modes | OpenRouter API key |

## Use it

```shell
git clone --depth 1 https://github.com/paddockhq/paddock
cd paddock/bundles/opencode
openshell provider profile import -f providers/opencode-openrouter.yaml
export OPENROUTER_API_KEY=...   # your key; OpenShell stores it, the sandbox only sees a placeholder
openshell provider create --name openrouter-opencode --type paddock-opencode-openrouter --credential OPENROUTER_API_KEY
openshell sandbox create --name opencode \
  --from ghcr.io/anomalyco/opencode:2.0.21@sha256:6d3cebbaaeed11b9dd1ea6d2ca8a3ec17eb548c5aed37e17c7ae80fd8b2f22b2 \
  --policy policy.yaml --provider openrouter-opencode \
  --env OPENCODE_DISABLE_MODELS_FETCH=1 --env OPENCODE_DISABLE_AUTOUPDATE=1 \
  -- opencode -m openrouter/nvidia/nemotron-3.5-lightning:free
```

## Why these settings

- `OPENCODE_DISABLE_MODELS_FETCH=1` makes OpenCode use its built-in model list
  instead of downloading one from `models.opencode.ai`. Models that OpenRouter
  added after OpenCode 2.0.21 was built are not available until the bundle moves
  to a newer OpenCode.
- `OPENCODE_DISABLE_AUTOUPDATE=1` stops update checks. OpenShell also blocks a
  self-updated binary, because it pins each binary's hash on first use.
- NVIDIA's example OpenRouter profile allows every path on `openrouter.ai`. This
  bundle allows only the chat completions endpoint, because any allowed path is
  also reachable by every tool the agent runs (spec §6.2, R2).

## Tested with

See the latest CI run's compatibility report for the OpenShell releases and
architectures this bundle passes on.

OpenShell v0.0.x is not supported: its sandbox supervisor creates the network
namespace with `ip netns` from inside the image, and the official OpenCode image
is Alpine without iproute2 ([ADR 0001](../../docs/decisions/0001-ci-runners.md)).
