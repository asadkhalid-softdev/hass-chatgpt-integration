# Sensor history

Version 0.5.0 adds read-only tools for the Recorder data behind Home Assistant sensor charts. No additional ChatGPT login or subscription permission is needed. Historical results count toward your account usage and are sent to the selected ChatGPT model.

## Enable it

1. Push the update, redownload ChatGPT Assist in HACS from the default branch, and restart Home Assistant.
2. Open **Settings → Devices & services → ChatGPT Assist → Configure → Model and permissions**.
3. Enable **Allow read-only sensor history**.
4. Check **Allowed sensors for history**. Sensors and binary sensors are listed by name and entity ID. Nothing new is selected automatically. Saved unavailable sensors remain listed so you can revoke them.
5. For bulk selection, check **Select all listed history sensors** or **Select none (history sensors)** and submit. Review the refreshed checklist, then submit again to save. Future discoveries are not automatically allowed.
6. Open the ChatGPT Assist sidebar or Assist and ask about a selected sensor.

History permission is independent of exposed-device control and automation/dashboard drafting. It grants no write capability. It requires an active, authenticated Home Assistant user with entity read permission. Unidentified satellite requests cannot query history. If configuration drafting is also enabled, the agent's existing administrator restriction still applies.

## Things to ask

- “What was the bedroom temperature overnight? Give me the minimum and maximum.”
- “Compare the living room temperature this week with last week.”
- “When did the bedroom humidity exceed 70% in the last 12 hours? Use recorded readings.”
- “Show the daily trend for my outdoor temperature over the last month.”
- “When did the window sensor change state this morning?”

Use sensor names; the assistant can discover the names and IDs of only permitted sensors. These tools provide data for a textual answer. Rendering new charts in the chat panel is not part of this update.

## Data and limits

- **Raw:** retained state changes and, when available, the state at interval start. Maximum **24 hours per query**. Queries run in one-hour chunks and stop after **600 points**. Returned points include timestamps and state strings, without arbitrary entity attributes. Historical unit changes are not normalized; the reported unit is the current entity unit.
- **Hourly:** long-term statistics, maximum **31 days per query**.
- **Daily:** aggregated long-term statistics, maximum **366 days per query**.
- Statistics include available mean/minimum/maximum and, for cumulative sensors, state/sum/change. They use Recorder's display unit. Each query targets exactly one allowed entity and returns at most 600 points and approximately 96 KB of JSON. List discovery is paginated at 100 sensors.
- Start and end must be explicit ISO timestamps with timezone offsets. The assistant receives Home Assistant's configured timezone to interpret local dates. Statistics cover whole calendar buckets: boundary buckets can include readings outside the exact requested time interval. Hourly/daily averages are aggregates, not individual readings or proof of an exact threshold crossing time.
- Missing history can mean Recorder exclusions, retention/purging, missing readings or unsupported statistics. Empty/missing intervals are never filled with zeros. Truncated responses are explicitly marked; the model is instructed to describe the limitation or request a smaller interval. A full high-frequency interval may require several smaller queries; the existing per-turn tool budget still applies.
- There is no SQL, database mutation, arbitrary statistic ID access, retention change or history deletion tool. External statistics that have no sensor entity are unsupported. The selection list does not promise that every selected sensor has retained history or long-term statistics.

Permissions are checked on every tool call and again before returning queried data. Previous history tool results are checked before being sent back to the model on a later turn. After revoking access, clear the conversation history to start fresh. Revoking a grant does not erase information already returned to ChatGPT or previously saved in your private chat history/traces.

Recorder is an optional integration dependency: normal chat works without it, while history queries explain that Recorder is unavailable. Database reads use Recorder's executor. Time ranges, result size and tool calls are bounded; the underlying Core history API can still retrieve many readings within an hourly chunk for very fast sensors. Prefer statistics or smaller raw intervals for those sensors.

Tested against Home Assistant Core 2026.3.4 and 2026.10.1, including SQLite Recorder reads. Test questions against your own sensors after updating; no live account query is performed by the automated tests.

Home Assistant references: [History](https://www.home-assistant.io/integrations/history/) and [long-term statistics](https://www.home-assistant.io/docs/configuration/long-term-statistics/).
