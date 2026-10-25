# Reasoning effort

After updating to 0.8.0 and restarting Home Assistant, open **Settings → Devices &
services → ChatGPT Assist → Configure → Model and permissions** and choose **Reasoning effort**
below the model. Save to apply it to Assist, sidebar chat, and Alexa requests.

| Setting | API value |
| --- | --- |
| Model default | Omit the reasoning parameter |
| None | `none` |
| Minimal | `minimal` |
| Low | `low` |
| Medium | `medium` |
| High | `high` |
| Extra high | `xhigh` |
| Maximum | `max` |

Lower effort generally favors speed and fewer reasoning tokens. Higher effort can
help with difficult questions but takes longer and can consume more allowance.
This controls reasoning, not the answer's length or Alexa's spoken length budget.
The existing 90-second request and 180-second turn limits still apply.

The selector lists documented API values and filters known incompatible choices:
GPT-6.1 Sol does not offer `none` or `minimal`. Model changes are validated when
saving, and existing incompatible settings fail locally before any API request.
Reopening settings suggests Model default for an incompatible saved value; Submit
is required to save that replacement. Other model/account restrictions can still
produce provider errors. The reasoning guide documents `medium` as its default. Choose **Low** to try faster replies on
this model, or leave **Model default** to preserve the existing provider behavior.
The ChatGPT plan route may impose additional restrictions. Unsupported settings
surface an error; the integration does not silently downgrade or retry a turn.

The selected value is sent as `reasoning: {"effort": "low"}` (for Low) on every
model request, including subsequent tool rounds. Existing installations without
this option omit the parameter, and their saved permissions and Alexa pairings
are unaffected. Changing it does not clear conversation history.

Options verified against the [official OpenAI reasoning guide](https://developers.openai.com/api/docs/guides/reasoning)
on October 25, 2026. New API values require an integration update.
