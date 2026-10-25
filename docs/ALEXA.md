# Alexa voice bridge

The custom HTTPS skill endpoint runs inside ChatGPT Assist. No Lambda, cloud bridge,
separate add-on, or HA bearer token is required. It is disabled until an administrator
enables it and pairs the originating Alexa account and each Echo.

## Behavior

Alexa recognizes the utterance and sends the question slot, locale, account and device
identifiers in a signed request. The integration verifies it, persists a deduplication
record, schedules work in Home Assistant, and immediately closes the skill with
“Let me check.” Generation does not wait inside the skill request.

Alexa and the sidebar share the configured HA user/assistant's conversation session
and saved model context. New voice questions can refer to earlier sidebar or voice turns.
The current voice turn receives additional voice-specific instructions, which are removed
from the active session afterward so normal chat retains its usual response style.
Alexa answers directly without follow-up or clarification questions.
The prompt includes Home Assistant's current local timestamp and configured timezone.
Unspecified periods use the current calendar period (for example, an unspecified month
means the current month); a named month without a year uses the current year. Explicit
dates and relative periods such as last month take priority. Latest/last-event questions
use actual available readings/history, never invented timestamps. Ambiguous informational
requests use reasonable assumptions; unresolved action targets are declined without a
follow-up question. These are model instructions, not a guarantee of model compliance.

The user question and answer are appended to the selected HA user's existing sidebar
transcript, labelled Alexa. Voice user messages begin with `via-Alexa: ` in both the
transcript and new model context. The prefix identifies the source and grants no extra
authority. The sidebar refreshes external messages automatically without changing its
composer. Ordinary chat turns can refer to new Alexa turns, too.

History remains scoped to the configured HA user and assistant. All paired Echos using
that configuration share this context, including that user's earlier private sidebar
messages. Clearing sidebar history resets the shared conversation. Requests are serialized
with sidebar sends so simultaneous turns cannot overwrite each other.

Alexa transcripts created before 0.9.0 remain visible and gain the displayed prefix.
Those older transcript-only turns are not retroactively injected into native model/tool
context; previously saved sidebar inference context is preserved, and new Alexa turns
join it going forward.
Normal sidebar messages retain their existing conversation behavior and never trigger
Alexa notification delivery.

Only the originating device's explicitly paired `alexa_media` entity receives the reply,
through `notify.alexa_media` with `type: tts`. No “last called” lookup or broadcast fallback
is used. The notification does not reopen the microphone. Ask the skill again for another
question; it will use the shared conversation history.

## Home Assistant setup

1. Update the integration and restart Home Assistant.
2. Ensure Alexa Media Player is installed, authenticated, and provides the
   `notify.alexa_media` service. Test its TTS action on the intended Echo.
3. Open **Settings → Devices & services → ChatGPT Assist → Configure → Alexa voice bridge**.
4. Enable the bridge. Copy your own Skill ID from the Alexa Developer Console
   (format: `amzn1.ask.skill.YOUR-SKILL-ID`). This is an identifier, not a secret key;
   new installations leave it blank until you enter it. Choose the HA user whose permissions and
   private sidebar transcript should be used, and save. Alexa speakers do not authenticate
   individual household members: anyone able to speak to a paired Echo uses this chosen
   HA actor. Existing agent tools/permissions apply, including administration/log tools
   if the selected user and integration permit them.
5. Open the skill on one physical Echo. It speaks a six-digit pairing code.
6. Reopen Alexa settings. Select the exact code spoken by that Echo and its corresponding
   Alexa Media Player name, then save. New Echos appear first, with the most recently heard first.
   Paired devices show their existing names. After updating from 0.7.0, open the skill
   again on an unpaired Echo to give its old discovery a spoken code. You can select an
   already paired device again to correct its target.
   The developer simulator is a different device; do not map it to a physical Echo unless
   you deliberately want simulator requests spoken there.
7. Disable the bridge to revoke voice access. Changing the skill ID clears account/device
   bindings. Removing the integration entry removes its stored bridge configuration.

These settings are stored separately from normal model/chat options; saving them does
not reset the stable sidebar configuration or reload the conversation agent.

## Alexa Developer Console

For skill **Alexa-AI-Hass**, invocation **mister jarvis**:

1. Use a **Custom** interaction model and a self-hosted **HTTPS** endpoint.
2. Under **Interaction Model → JSON Editor**, import [en-US.json](alexa/en-US.json), save
   and build. Keep your preferred invocation name when importing. The supplied name is
   `mister jarvis`. It uses `QuestionIntent` with an `AMAZON.SearchQuery` slot named
   `question`, a dialog model with manual delegation, and a bare `{question}` **slot sample**.
   Import the whole model, including `dialog` and `prompts`; these are required by the
   integration's `Dialog.ElicitSlot` response. The bare sample is not an intent sample.
   The supplied model is English (US), matching the current skill. Other Echo locales
   require their own translated model.
3. Under **Endpoint**, choose HTTPS and set Default Region to:

   ```text
   https://ha.example.com/api/chatgpt_assist/alexa
   ```

   Replace `ha.example.com` with your own public Home Assistant domain.
   Select the trusted certificate-authority option for your publicly trusted TLS certificate
   (for example, a Let's Encrypt certificate). Save. Do not enter an HA token in this URL.
4. Enable **Development** under **Test**. In the Alexa app, use **Your Skills → Dev** and
   enable the skill with the same Amazon account as the Echo. Public publication and
   OAuth account linking are not needed for this paired private installation.
5. Open the skill and pair devices as above. Then try:

   - “Alexa, ask mister jarvis what's the bedroom temperature.”
   - “Alexa, ask mister jarvis to tell me the average bedroom temperature last night.”

### Natural questions

Update the Alexa model and ChatGPT Assist to 0.7.2, then restart Home Assistant.
After “Alexa, open mister jarvis”, the short “What would you like to know?” prompt
explicitly elicits the entire question slot. Ask naturally, for example:

- “When was the last time work heater turned on?”
- “How long was the work heater on yesterday?”
- “Compare the bedroom and kitchen temperatures.”
- “Is the bedroom warmer than yesterday?”

Help, fallback, and empty questions re-enter question collection. Stop and cancel
still end the session. A valid question immediately closes the session with
“Let me check”, followed by the asynchronous reply as before.

One-shot requests (e.g. “Alexa, ask mister jarvis when was the last time the work heater
turned on”) have broader carrier patterns, but remain dependent on Alexa intent
recognition. Carrier words may be omitted from their question slot. The open-then-ask
flow is preferred for capturing the complete question. This is still Alexa speech
recognition, not a raw audio or guaranteed verbatim transcript feed; misrecognition,
Alexa built-in commands, and session timeouts can still interrupt collection.

References: [Dialog directives](https://developer.amazon.com/en-US/docs/alexa/custom-skills/dialog-interface-reference.html),
[SearchQuery slot rules](https://developer.amazon.com/en-US/docs/alexa/custom-skills/slot-type-reference.html).
Verify recognition on the actual Echo after updating both sides.

NGINX Home Assistant SSL proxy should already forward this `/api/` path to HA. No new
port or service route is needed. Verify public port 443, a valid full certificate chain,
and that NGINX preserves `SignatureCertChainUrl` and `Signature-256`. An ordinary browser
GET to the endpoint is not a valid test: the endpoint accepts only signed POSTs.

## Spoken length

**450 characters is our default conservative budget, not a verified Amazon API maximum.**
It is configurable between 200 and 1,000 characters. The model is instructed to provide
a short plain-text spoken answer within this budget. The delivery code additionally
removes Markdown, links and markup, escapes XML, and caps the final payload. Oversized
answers get a shortened spoken version with a chat reference; the full generated answer
remains in the sidebar, subject to its existing 16,000-character storage bound.

Amazon documents a 10,000-character limit for a custom skill's normal `outputSpeech`;
that is a **different delivery API** from Alexa Media Player notifications. We found no
authoritative published maximum for Alexa Media Player's unofficial TTS notification
path. Do not claim the skill limit applies to notifications. Validate the configured
budget on the target devices/region and lower it if necessary.

- [Amazon skill speech limits](https://developer.amazon.com/en-US/docs/alexa/custom-skills/guidelines-ux-amazon-polly-skills.html)
- [Alexa Media Player notification implementation](https://github.com/alandtse/alexa_media_player/blob/dev/custom_components/alexa_media/notify.py)
- [AlexaPy documentation and unofficial API caveat](https://alexapy.readthedocs.io/en/stable/index.html)

## Security and failure handling

- SHA-256 request signatures over the original HTTP body, trusted certificate chains,
  `echo-api.amazon.com` certificate identity/expiry, timestamps within 150 seconds, and
  exact skill/account/device authorization. Signing certificates can only be fetched
  from HTTPS `s3.amazonaws.com/echo.api/…pem`, without redirects, bounded to 32 KB.
- Four concurrent intake requests, two certificate verifications, 32 discovered pairing
  candidates, four background jobs, and one job per Echo at a time. Question length is
  capped at 4,000 characters. Requests are capped at 32 KB and intake at six seconds.
- Accepted request IDs are hashed and persisted for 24 hours (up to 1,024 daily jobs).
  Alexa retries do not repeat generation, device actions or notifications. Pending jobs
  are not rerun after HA restart. Background work is cancelled when its entry unloads.
- Delivery rechecks the selected HA user, configuration snapshot and Echo mapping.
  Chat delivery metadata reports notification submission or failure. Submission does
  not prove that a physical speaker played it: Amazon, offline devices, DND or expired
  Alexa Media Player authentication can prevent playback. No automatic TTS retry is made.
- A failed model request can follow successful tool actions. Check device state before
  submitting the same question again. This endpoint does not bypass existing tool grants.

The handler uses `requires_auth=False` only for this one route because Alexa does not
send HA's normal authorization header. Amazon signature verification and explicit
pairing replace that middleware on this route; existing HTTP/WebSocket routes stay
authenticated. Certificate validation runs off HA's event loop. No signing headers,
questions, provider tokens or certificate bodies are logged by the bridge.

## Live verification checklist

- Enable and pair one real Echo; confirm an unpaired Echo cannot trigger inference.
- Ask for a known sensor reading; check that only the requesting Echo speaks it and
  the same user/answer appear in the selected user's open sidebar.
- Put a harmless fact in sidebar chat, ask Alexa about it, then ask a sidebar follow-up
  about the voice reply. Confirm shared context and the `via-Alexa:` prefix.
- Clear sidebar history and confirm Alexa no longer receives that context.
- Send a normal sidebar message; confirm it stays silent on every Echo and normal chat
  context continues to work.
- Try a slow historical question; confirm the skill closes promptly and the eventual
  answer arrives by TTS.
- Test a long answer, notification failure and bridge disablement during generation.

Automated tests cover signed HTTP requests using a local test CA, tampering, timestamps,
SSRF rejection, account/device pairing, replay/reload, history isolation, voice-only
instructions, transcript visibility, length budgets and delivery failure. Live Amazon
signature/certificate compatibility and physical Echo playback need the installed update.
