# Invocation examples

Explicit nightly entrypoint; installing a schedule is a separate authorized action.

- [Nightly command](nightly.sh) — Run one bound replica explicitly.

First baseline and review a dry run using the root README. Then an authorized scheduler can invoke:

```bash
/path/to/agent-session-tools/examples/nightly.sh /path/to/replica \
  /path/to/native/sync.log /private/state/cursor.json America/Boise
```

Keep JSON output in private state. Exit 2 requires attention; do not reset the cursor automatically. This example installs nothing and reads no credentials.
