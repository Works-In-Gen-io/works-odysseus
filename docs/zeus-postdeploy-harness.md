# Zeus post-deploy canary harness

This runbook is intentionally inert until the canary is authorized. It never
stores or prints the Zeus token.

## Preconditions

Set the token only in the current terminal process:

```bash
export ZEUS_ODYSSEUS_URL='https://<zeus-host>'
read -r -s 'ZEUS_ODYSSEUS_API_TOKEN?Zeus token: '; echo
```

The token must not be written to a file, shell history, repository, or report.

## Phase 0 — scoped post-deploy preflight

Run the existing integration helper:

```bash
python3 ~/plugins/odysseus-zeus/scripts/odysseus_api.py capabilities
```

Record only the JSON response, HTTP success/failure, token scopes, and tool
availability. Redact the URL path if it contains deployment-specific detail;
never record the bearer token.

## Phase 1 — Codex runtime matrix

These cases must be executed from Codex with the `odysseus-zeus` integration
enabled. They are not HTTP `/api/codex` operations, so the harness must not
pretend that a capabilities response proves them.

| ID | Operation | Expected evidence |
|---|---|---|
| A | Direct model call using DeepSeek | `EXECUTED`, model/provider, response id or bounded response fingerprint, no token |
| B | `create_session` using DeepSeek | `EXECUTED`, session id, model, endpoint label; no headers |
| C | Reload that child session, then `send_to_session` | `EXECUTED`, same session id, successful response; no 401 |
| D | Direct model call using OpenRouter | `EXECUTED`, model/provider, response id or bounded response fingerprint, no token |
| E | `create_session` using OpenRouter | `EXECUTED`, separate session id, model, endpoint label; no headers |
| F | Reload the OpenRouter child, then `send_to_session` | `EXECUTED`, same session id, successful response; no 401 |
| G | Durable readback from a fresh session | Reopen/read the real stored result, compare session id and bounded response fingerprint; no secret/header data |
| H | Create a valid due `llm/once` canary task | Task id, `scheduled_date`, `next_run`, active status |
| I | Observe exactly one unattended run | Task id, run id, `run_count=1`, `last_run`, final next-run/status |

For A–G, use the Codex tools directly and keep the prompts deterministic, for
example `Reply with exactly CANARY-DEEPSEEK-OK` and
`Reply with exactly CANARY-OPENROUTER-OK`. Do not include credentials in the
prompt or ask the model to echo configuration.

For G, create or identify the session/result, discard the in-memory session
object, open a fresh session context, reread the durable result, and compare
only stable non-secret fields and the bounded response fingerprint. A cached
object or a successful prior call is not durable-readback evidence.

For H–I, use a date sufficiently in the future for creation, then wait until
the due time only after the separate unattended-canary authorization is given.
Do not use `latest` or a real user task as evidence.

## Structured evidence

Save a report outside the repository with this shape, omitting secrets:

```json
{
  "target": "Zeus",
  "integration": "odysseus-zeus",
  "post_deploy_sha": "<immutable image source SHA>",
  "preflight": {"status": "PASS", "scopes": [], "tools": {}},
  "checks": {
    "direct_deepseek": {"status": "NOT_RUN"},
    "create_session_deepseek": {"status": "NOT_RUN"},
    "reload_send_deepseek": {"status": "NOT_RUN"},
    "direct_openrouter": {"status": "NOT_RUN"},
    "create_session_openrouter": {"status": "NOT_RUN"},
    "reload_send_openrouter": {"status": "NOT_RUN"},
    "durable_readback": {"status": "NOT_RUN", "comparison": "NOT_RUN"},
    "llm_once_canary": {"status": "NOT_RUN"}
  },
  "secret_persisted": "NO/UNKNOWN",
  "deployment_performed": "NO"
}
```

Accept only `EXECUTED` evidence from the Codex tool result or a readable,
immutable readback. `configured`, `available`, or a green UI indicator alone is
not a successful canary.

## Cleanup

```bash
unset ZEUS_ODYSSEUS_API_TOKEN ZEUS_ODYSSEUS_URL
```

Do not delete the canary task or session until their identifiers and final
state have been recorded, unless the separate canary authorization requires
cleanup.
