# Native administrator logs

Version 0.6.0 adds built-in read-only log tools. **Allow administrator access to all available native logs** starts enabled. It needs no extra ChatGPT sign-in, long-lived HA token, plug-in or external log viewer. Only an active, authenticated HA administrator receives the tools; household users can still use ordinary chat/device control when configuration administration is off.

Update in HACS, restart HA and refresh the browser. Open **Configure → Model and permissions** to disable log access if desired. The sidebar header shows **Admin logs enabled** for eligible administrators.

## Included sources

| Source | Availability |
|---|---|
| Core condensed warnings/errors | Native `system_log` records, including occurrence counts and tracebacks |
| Core live log buffer | Recent records since this integration loads, at the existing logger levels; works without a persisted Core log file |
| Core/integration log files | Native logger files and `.log`, numbered rotations and `.log.fault` files directly in the HA configuration directory |
| Activity / Logbook | Native recorded activity, in explicit intervals up to 24 hours per query |
| Automation and script traces | Native trace summaries and detailed runs, including errors and execution paths |
| Core and Supervisor container logs | Native Supervisor API on installations with Supervisor |
| Installed app/add-on logs | Discovered from Supervisor, including services such as MQTT, ESPHome or Zigbee2MQTT when installed as apps |
| Host system journal | Host logs, discovered journal identifiers such as NetworkManager/kernel, and previous boot offsets |
| Supervisor plugins | Native audio, CLI, DNS, multicast and observer log endpoints when supported |

`logs_sources` returns the installation's catalog, paginated at 100 sources. `logs_read` accepts a discovered source, line count, recent-window offset and literal search. Activity accepts ISO timestamps; traces accept item/run IDs; Supervisor sources accept past boot offsets. Sources that are absent, unsupported or no longer retained are reported rather than fabricated. Native Supervisor endpoints are verified when read; listing an endpoint does not guarantee the host's journal backend supports it.

Try:

- “List the log sources you can access.”
- “Check Core and Supervisor logs for why my automation didn't reload.”
- “Inspect the latest trace of my humidity automation and explain where it stopped.”
- “Check MQTT app logs and the host network logs for connection failures.”
- “Look at the previous boot's host logs for why Home Assistant restarted.”

## Limits and privacy

A read returns up to 500 lines and 64 KB of text. File/API scans are capped at 512 KB; file reads use a tail window and Supervisor requests use bounded line counts. The live buffer retains at most 5,000 records/512 KB and is removed when the last enabled integration account unloads. It changes no logger levels and cannot recover messages from before capture started. Condensed records, activity and trace data are obtained through their native interfaces; activity database queries and trace serialization can materialize more data than the final returned window.

Search filters a bounded window. An empty search result does not prove a message never occurred; ask for another page, boot or narrower activity interval. These tools do not enable debug logging, clear records, mutate retention, run commands or read model-supplied filesystem paths. Existing HA logger levels and recording settings determine what is available. Archived gzip logs, remote device/cloud logs and arbitrary Docker/host logs outside HA's native interfaces need separate adapters or host access; they are not automatically accessible.

Queried logs and traces are sent to your selected ChatGPT account and can remain in your private sidebar conversation and HA traces/backups. Known OAuth/Supervisor credentials and common password/token/API-key/cookie/private-key patterns are redacted before tool output is returned. **Redaction is best-effort:** arbitrary third-party messages can still contain secrets or private household data without recognizable labels. Disable log access if this is unsuitable for your installation.

Permissions are checked before and after reading. A later turn cannot forward old log results after log access is disabled or the user loses administrator privileges. The sidebar also protects saved administrator history after demotion. Clear history to start fresh; disabling access does not erase already returned data or existing archives.

Native references: [System Log](https://www.home-assistant.io/integrations/system_log/) and [Supervisor log endpoints](https://developers.home-assistant.io/docs/api/supervisor/endpoints/).
