# Jyotish Consultant Web

This is a remote-first plugin package for ChatGPT and Codex. It contains the
conversation policy and an MCP connection template; it does not contain birth
profiles, local filesystem assumptions, credentials, or an app registration.

## Remote MCP contract

`.mcp.json` deliberately uses the `JYOTISH_MCP_URL` template rather than a
made-up deployment address. Resolve it to the deployed streamable-HTTP MCP
endpoint (for example, an endpoint ending in `/mcp`) before a host uses this
file. The skill is fail-closed: it uses only the advertised `calculate` tool
and never assumes private or persisted profile access.

The intended public MVP surface is exactly one stateless, read-only tool:
`calculate`. It requires a complete inline birth profile. `jaimini`,
`prashna`, `muhurta`, profile lookup, source search, ResearchRuns, inspection,
and every `*_full` tool are unavailable in this MVP. A separate reviewed
release is required before any of them can be added.

The public call uses the advertised `request` envelope with
`request.profile="inline"`, a complete `request.inline_profile`, and the
focused question/scope fields. Do not rely on the server's inline default.

The plugin bundle, rather than a generic MCP server, is what carries this
conversation policy. Deploying the repository's MCP server alone does not make
a local repository `SKILL.md` available in ChatGPT or Codex.

## Deployment acceptance

At the initial ChatGPT **Scan Tools**, verify that the remote connection exposes
exactly `{calculate}`. It must not expose `get_profile`, `search_sources`,
`research`, `finalize_research`, `inspect_research`, `jaimini`, `prashna`,
`muhurta`, or any `*_full` tool.

Treat the scan result and installed plugin skill as snapshots. After changing a
tool surface, its schema, the remote URL, or this packaged skill, scan/register
the MCP connection again and refresh or reinstall the plugin before retesting
in a new chat.

## ChatGPT web handoff after Railway deploy

1. Verify the Railway HTTPS endpoint and MCP tool discovery.
2. In ChatGPT Developer Mode, register that MCP server connection.
3. Copy the resulting `plugin_asdk_app...` technical ID.
4. Add an `.app.json` that maps the plugin to that registered ID, then add the
   corresponding `apps` entry to `.codex-plugin/plugin.json`.
5. Test the installed plugin in a new chat with an inline birth profile.

No `.app.json` is included yet because an app ID is issued only after the
ChatGPT connection is registered.
