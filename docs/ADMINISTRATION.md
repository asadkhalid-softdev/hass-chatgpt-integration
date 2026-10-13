# Automation and dashboard administration

Version 0.2.0 adds opt-in configuration tools. The assistant can read complete allowed automation definitions, including triggers, conditions and actions, and inspect an allowed dashboard's views and cards. It can prepare changes and explain them. An administrator must review and approve each change in Home Assistant; saying “approve” in chat does not apply a draft.

## Enable access

1. Update ChatGPT Assist in HACS and restart Home Assistant. If HACS does not offer an update, open its ChatGPT Assist page, use the menu to **Redownload**, select the current version/default branch, and restart.
2. Open **Settings → Devices & services → ChatGPT Assist → Configure → Model and permissions**.
3. Enable **configuration inspection and drafts**. This permission is separate from exposed-device control.
4. Expand **Automations** (closed initially) and check the **Allowed automations** you want to grant access to. The checklist displays each automation's name and configuration ID; blueprint entries are marked read-only. Entries from the standard editor file and Home Assistant’s loaded automations are listed. Automations from packages/custom includes or unsupported editor files are marked read-only. Automations without configuration IDs use their entity ID for read-only selection. You do not need to find or type IDs for existing automations.
5. Expand **Dashboards** (closed initially) and check the **Allowed dashboards** by title. Only existing storage-mode dashboards are listed. Saved grants stay selected, including reserved or unavailable entries, so updates do not silently change permissions. Uncheck an item to revoke its access. If editor-file discovery cannot run, loaded automations still appear. The form explains the specific editor-access restriction and preserves previous selections.
   To select a whole list, check **Select all listed automations/dashboards** or **Select none (automations/dashboards)** and press **Submit**. The form returns with updated checkboxes and the bulk controls reset. Review or adjust the selections, then submit again to save. Select all covers the currently listed entries, including reserved/unavailable grants; newly discovered resources remain unselected. Select none for automations also clears the new-ID reservation field. Choose only one bulk control per list.
6. Save. Start a new Assist conversation while signed into HA as an administrator.

To authorize creation of a new automation, optionally enter an ID such as `ai_morning_lights` in **Reserve IDs for new automations**. Separate multiple IDs with commas; use letters, numbers, underscores or hyphens. The IDs join your saved selections and appear as reserved entries in the checklist until created. Leave this field empty when selecting existing automations.

Versions before 0.2.1 stored comma-separated grants. They remain valid and are displayed as preselected checklist entries; saving converts them to lists without granting additional targets.

There is no wildcard access. Empty lists grant no configuration targets. When configuration administration is enabled, this conversation agent is restricted to active, authenticated administrators to keep configuration conversation history private. Non-administrator, inactive, system-generated and unidentified requests are rejected before contacting the model. Voice requests from satellites without a user identity cannot administer configuration. Existing Assist device controls retain their normal exposure rules. Keep configuration administration disabled on an assistant intended for household members or unidentified satellites.

## Inspect and prepare changes

Try:

- “Read automation 1700000000000 and explain its triggers and conditions.”
- “Optimize automation weekday_morning to avoid repeating the action. Preserve its behavior and prepare a draft. Explain the tradeoff.”
- “Create automation ai_morning_lights: at 07:00 on weekdays, turn on light.kitchen. Prepare it for review.”
- “Read dashboard dashboard-home. Prepare a draft adding a view with my existing light entities. Preserve the other views.”

If targets or behavior are unclear, provide them explicitly. The assistant should inspect existing configuration before editing it. It submits complete JSON replacements; unrelated fields must be preserved in the draft. Proposals expire after **30 minutes**. The account still has its normal usage limits, and a turn is limited to eight tool calls.

## Review and apply

1. The assistant returns a proposal ID. Open **ChatGPT Assist → Configure → Review changes**.
2. Select that proposal, leaving **Restore saved backup** off.
3. Read the full diff. Check every trigger, condition, action, entity target and dashboard setting. The server uses the saved draft, not a chat approval or editable replacement text.
4. Check **I have reviewed the configuration and approve this operation**, then submit.
5. Automations are saved atomically and the automation reload service is awaited. Dashboards are saved through HA's own dashboard storage interface. Check the result in the normal editor and test the intended behavior.

A changed target, expired draft, revoked permission, changed ID or failed validation blocks application. A draft is never silently rebased or automatically retried. Dashboard validation checks the JSON structure; the frontend determines whether individual standard or custom cards render correctly. Installing custom card resources is outside this workflow.

Avoid simultaneous edits in the automation/dashboard editors while applying a proposal. Conflict checks compare the target before writing, and the automation file is checked again immediately before atomic replacement. HA's native editors and external file editors do not share the integration's mutation lock; these checks are not a cross-editor transaction.

## Restore a backup

Open **Configure → Review changes**, select an applied proposal, enable **Restore saved backup**, and review/approve. The displayed original-to-proposed diff is reversed for restoration. A newly created automation is removed when restoring its previous absent state. The target must still match the applied draft; later human changes block restoration so they are not overwritten.

If saving or reloading failed, the proposal is marked failed and its saved configuration remains available. Verify the actual state first. If the proposed configuration was saved, the same restoration workflow can restore it; if nothing changed, create a fresh draft. After a restart during application, an `applying` record can also be restored when its live configuration matches the draft. There are no automatic rollback retries.

The integration retains at most **20** proposal/backup records per account. Older completed or expired records can be discarded as new drafts arrive. Backups are stored in `.storage/chatgpt_assist.<entry_id>.administration`, with HA's private storage option. They are local JSON, not an encrypted vault or a replacement for Home Assistant backups. Removing the integration removes this store.

## Supported scope

- **Automations:** read, create and replace entries in the standard UI editor file, with `automation: !include automations.yaml` in `configuration.yaml`. HA's automation validator checks drafts before application. Configuration must be JSON-compatible. Applying uses the same atomic YAML file-writing utility as HA's editor, so comments/formatting in `automations.yaml` can change.
- **Blueprint automations:** inspect their saved blueprint reference and inputs; editing or expanding blueprint definitions is unsupported. Their triggers may be defined in the referenced blueprint rather than the saved entry.
- **Dashboards:** inspect and replace configuration of existing storage-mode dashboards, including adding or editing views/cards. Take control of an automatically generated dashboard in its editor first. Creating dashboard registrations, changing sidebar metadata and editing YAML dashboards are unsupported.
- **Package/custom-include automations:** read-only inspection from the original source location recorded by Core. Secret/include tags are returned as reference metadata, never resolved values. The source must remain inside the HA configuration directory and match the loaded automation identity. Reload automations after moving their source.
- **Other configuration:** no package/include editing, secret-tag resolution, integration installation, arbitrary file access, template execution, shell access or general administrative service tool. Automations and existing scripts can have broad effects; inspect their actions before approval.

Allowed configurations and proposal arguments are sent to your selected ChatGPT account when tools are used and may appear in HA conversation traces. Grant only targets you are comfortable sharing. Avoid literal credentials in those configurations. YAML secret/include tags prevent rewriting the automation editor file. Read-only source inspection returns tag/reference metadata instead of resolving secrets or includes.

This capability is tested locally against Core 2026.3.4 and 2026.10.1. It uses internal HA automation validation and dashboard storage interfaces, which may change in future Core versions. A live test on your installation is still needed after updating.
