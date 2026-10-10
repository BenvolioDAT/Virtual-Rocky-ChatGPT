# desk-robot

A small desk robot with a face, a voice, and a camera. Say "hey Rocky" and it
turns its head, looks at you, and answers out loud in character. The body is
a $24 microcontroller with an OLED screen on a pan-tilt neck. The brain is a
Python program on your computer that does speech-to-text, asks a language model,
and speaks the reply through the robot's speaker.

<!-- photo or short clip goes here: docs/rocky.jpg -->

## Versions

**V1 is the robot in the videos.** It is frozen as the
[v1.0 release](https://github.com/cgro00/desk-robot/releases/tag/v1.0), a
permanent snapshot of the code, wiring, and parts list as built. `main` is
always the latest version and may be ahead of what an older video shows.
[CHANGELOG.md](CHANGELOG.md) lists what changed between versions.

Out of the box it is **Rocky**, the Eridian engineer from *Project Hail
Mary*: short sentences, "question" and "answer", "amaze", and constant
worry about whether you have slept. Everything about him is yours to change.
See [Make it your own](#make-it-your-own).

**What it can do**

- Wake on its name, listen, and answer with a spoken reply in a cloned voice.
- Show seven expressions on its face, blink, and doze off when ignored.
- Turn and nod its head, follow your face, and look where you ask.
- See through its camera and tell you what is there, honestly.
- Decide when you have finished talking, the way a person does, instead of
  waiting for a fixed pause.

**How it is put together**

```
┌──────────────── the robot (XIAO ESP32S3 Sense) ───────────────┐
│  OLED face · pan/tilt servos · camera · mic · amp + speaker   │
└───────────────────────────┬───────────────────────────────────┘
                            │ WiFi (WebSocket)
┌───────────────────────────┴───────────────────────────────────┐
│  brain server (Python, on your computer)                      │
│  wake word → speech-to-text → language model → text-to-speech │
│  plus face tracking, emotions, and head movements             │
└───────────────────────────────────────────────────────────────┘
```

The firmware is deliberately simple: it draws the face, moves the servos,
and streams audio and camera frames. All the judgement lives in `server/`.
Nothing is billed while the robot is idle.

## Contents

1. [What you need](#what-you-need)
2. [Build the body](#build-the-body)
3. [Flash the firmware and test over USB](#flash-the-firmware-and-test-over-usb)
4. [Set up the brain on your computer](#set-up-the-brain-on-your-computer)
5. [Connect the robot to the brain](#connect-the-robot-to-the-brain)
6. [Living with Rocky](#living-with-rocky)
7. [Make it your own](#make-it-your-own)
8. [Troubleshooting](#troubleshooting)
9. [How it works](#how-it-works)
10. [Privacy and security](#privacy-and-security)
11. [Credits and license](#credits-and-license)

## What you need

**Parts.** Roughly $100 in total, plus a soldering iron if you do not have
one. Everything is a common Amazon or Adafruit item.

| Part | Notes |
| --- | --- |
| Seeed XIAO ESP32S3 **Sense** | The Sense version has the camera and microphone built in. Get it with headers pre-soldered if you can. The little U.FL antenna in the box is required for WiFi. |
| 1.3" SH1106 I2C OLED, 128x64 | The face. The 0.96" SSD1306 also works with a one-line firmware change. |
| Adafruit Mini Pan-Tilt kit, assembled | The neck. It ships with two SG90 servos, which work. MG90S metal-gear servos are a drop-in upgrade for smoother motion. |
| MAX98357A I2S amplifier board | Turns digital audio into speaker power. The $3 clones work. |
| Small 4 Ω 3 W speaker | Enclosed ones with a JST lead are easiest to mount. |
| 470 to 1000 µF electrolytic capacitor | Keeps the servos from browning out the board. Not optional. |
| Breadboard, jumper wires, M2/M2.5 nylon standoffs | For wiring and mounting the screen. |
| 5 V, 2 A or better USB-C power supply | A laptop port is fine for flashing, not for running servos and speaker. |

**On the computer side.**

- A Mac, Windows PC, or Linux machine on the same WiFi as the robot. It was
  built and tested on an Apple Silicon Mac. Windows and Linux use the same
  code except for the built-in fallback voice and speaker playback, which
  have their own paths that nobody has run yet. If you're the first, say how
  it went. On Linux, install `espeak-ng` for the fallback voice.
- Python 3.13, which is what this was built and tested with.
- PlatformIO for flashing the firmware (installed below).
- A language-model API key. Any one of these works:
  - **OpenRouter** (the default): one key, any model, easy to switch.
  - **Anthropic**: use a Claude model directly.
  - **OpenAI**: use a GPT model directly.
- Optionally a **Fish Audio** key for the cloned voice. Without it Rocky
  speaks with your computer's built-in voice, which is fine for getting
  started.

**Skills.** Basic soldering (about 27 joints, all through-hole), and the
patience to read the wiring guide before powering anything on.

## Build the body

Follow [`docs/wiring.md`](docs/wiring.md) with the parts in hand. The short
version:

1. Everything shares a ground rail.
2. Servos and the amplifier run from the XIAO's **5 V** pin, never 3.3 V.
3. The big capacitor goes across 5 V and ground, striped leg to ground.
4. The OLED is on I2C (D4/D5), the servos on D3 (pan) and D6 (tilt), the
   amplifier on D0, D1, D2.
5. The camera and microphone are on the Sense board already. No wiring.

Only the OLED and the XIAO ride on the pan-tilt head. The amplifier,
speaker, breadboard, and capacitor stay on the desk. There is no printed
shell yet, so mount the screen on a small plate on the tilt platform with
standoffs or foam tape, with the camera peeking over the top edge.

## Flash the firmware and test over USB

Do this before WiFi. It proves the face and the neck work.

1. Install PlatformIO, either as the VS Code extension or from the terminal:

   ```bash
   brew install platformio
   ```

2. Plug the XIAO in over USB-C, then build and flash:

   ```bash
   cd firmware
   pio run -t upload
   pio device monitor        # serial console at 115200
   ```

3. The eyes should open, blink, and look around on their own. In the serial
   console, try:

   ```
   help                 list commands
   emo happy            change the face: neutral/happy/sad/angry/surprised/sleepy/thinking
   pan -30              turn the head, -60..60, 0 = center
   tilt -20             nod the head, -60 (down)..0 (level)
   blink                blink once
   demo off             stop the idle behaviour
   raw tilt 20          calibration move that ignores the limits (watch it!)
   ```

4. Check the head's manners. If `tilt -20` looks up instead of down, flip
   `TILT_INVERT` in `firmware/include/config.h`. If the head is not straight
   or level at 0, adjust `PAN_TRIM_DEG` and `TILT_TRIM_DEG` a few degrees at
   a time. If the tilt bracket strains at the end of its travel, pull the
   `TILT_MIN_DEG` and `TILT_MAX_DEG` limits in. Re-flash after each change.

Without a `secrets.h` file the firmware stays in this USB-only mode, which
is useful whenever you want to test the body alone.

## Set up the brain on your computer

The brain works without the robot: it uses your computer's microphone and
speaker until the robot connects. Get it talking first.

```bash
cd server
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # Windows: copy .env.example .env
```

Open `server/.env` and fill in:

- `LLM_API_KEY`: your OpenRouter key. (For Anthropic or OpenAI instead, see
  [Change the model or provider](#change-the-model-or-provider).)
- `HUMAN_NAME`: what Rocky should call you.
- `ROBOT_TOKEN`: any random string. The robot will need the same one. Make
  one with `python3 -c "import secrets; print(secrets.token_hex(16))"`.
- `FISH_AUDIO_API_KEY`: optional, for the cloned voice.

Then start it, from the `server` folder with the venv active:

```bash
python -m brain.main
```

The first run downloads about 160 MB of speech models into `~/.cache`
(Whisper from Hugging Face, the two turn-detection models from GitHub and
Hugging Face, all pinned to a fixed version). macOS will ask once to let
your terminal use the microphone; on Windows, check that microphone access
for desktop apps is on in Privacy settings. Say **"hey Rocky, what is a
weekend?"** and he should answer through your computer's speaker. You can
also type `ask what is a weekend?` into the server console.

The live view at <http://localhost:8766/> is Rocky's console: what he sees,
what he hears, the last exchange, and controls for his head, face, voice,
sleep, and listening. It only answers this computer.

## Connect the robot to the brain

1. Find your computer's address on your WiFi:

   ```bash
   ipconfig getifaddr en0     # macOS
   ipconfig                   # Windows: the IPv4 address of your WiFi adapter
   hostname -I                # Linux
   ```

   Your router can usually pin the computer to a fixed address so this does
   not change.

2. Copy `firmware/include/secrets.h.example` to `secrets.h` in the same
   folder and fill in your WiFi name and password, that address, and
   the same `ROBOT_TOKEN` you put in `server/.env`. The ESP32 only sees
   **2.4 GHz** networks.

3. Flash again with `pio run -t upload`. The serial console shows
   `wifi: connected` and then `brain: connected` once the server is running.

From then on the server listens through the robot's microphone and speaks
through the robot's speaker whenever the robot is connected, and falls back
to your computer when it is not. The robot can now live on a wall supply
away from the computer.

## Living with Rocky

| Say | What happens |
| --- | --- |
| "hey Rocky" | He wakes, looks up, and waits for your question. His name alone, without "hey", does not wake him. |
| anything, while he is awake | He answers. No need to repeat his name for about a minute. |
| "Rocky, look left" / "look at the door" | He turns his head, takes a fresh picture, and tells you what he sees. |
| "what do you see?" | He describes the current camera frame, and only what is actually in it. |
| "track me" / "stop tracking" | His head follows your face, or stops. |
| "Rocky, sleep" / "goodnight" | He says goodnight and stops listening until you say his name. |

He decides you are finished the way a person does. A small model listens to
how your sentence ends; if you sound done he answers about a third of a
second later, and if you trail off he waits. His first sentence is spoken
while the rest is still being written. If you start talking again before he
speaks, he drops the reply and answers the whole thing once. Once he is
speaking he finishes the line, because his microphone is muted while his
own voice plays.

Server console commands, for when talking is inconvenient:

```
ask <question>       talk to Rocky from the keyboard
say <text>           speak exactly this
volume 0.5           speaker volume, 0 to 1
listen               toggle the microphone
mic                  three-second level meter
track on|off         face tracking
emo surprised        push a face
pan 20 / tilt -20    move the head
status               what is connected
```

Every reply prints a `timing` line so you can see where the seconds go.

## Make it your own

Everything below is a one-file edit. None of it needs the robot plugged in,
so you can tune the character with `ask` in the server console before the
body is even built.

### Rename the robot

`ROBOT_NAME` in `server/brain/config.py`. The wake word becomes "hey
<name>" and the sleep phrases and speech-to-text hint follow automatically.
Update `WAKE_PHRASES` in the same file with the ways speech-to-text tends
to mishear the new name (say it a few times and watch the console). The
character file still introduces itself as Rocky, so edit
`server/brain/personality.py` too, or you have a robot called Bolt who
insists he is Rocky.

### Change the character

`server/brain/personality.py` is the whole personality: one system prompt
that pins down who he is and how he talks, plus a few canned lines for
waking, sleeping, and tracking. To make a different character, rewrite the
prompt. The parts worth keeping are the rules about being honest with the
camera, the emotion tag at the start of every reply, and the sentence
limit, because the face, the voice, and the cost all depend on them. Add
real exchanges that came out well to the examples at the bottom; they do
more than the rules do.

`REPLY_MAX_SENTENCES` in `config.py` caps how much he says per turn. The
server cuts anything past it before it is spoken.

### Change the voice

Rocky's voice is a community-uploaded fan clone on
[Fish Audio](https://fish.audio), not something this project owns. It may
disappear one day, and it is for personal use. Open any voice's page there,
copy the reference ID from the URL into `fish_voice_id` in a `server/voices/` profile,
and put your Fish key in `server/.env`.
The profile's `temperature` and `top_p` trade steadiness for expressiveness.
Without a Fish key he uses the computer's built-in voice: on macOS,
`TTS_FALLBACK_VOICE` picks one (`say -v ?` lists them); Windows uses its
default voice; Linux uses `espeak-ng` if installed.

The robot's speaker is tiny, so a deep voice turns into rattle. Three knobs
in the selected voice JSON shape the audio before it reaches the speaker: `level`
(loudness he is held to), `highpass_hz` (bass cut, try 250 to 350 for a
deep voice), and `presence_db` (lift for a muffled voice). The console
page has sliders for all three so you can dial them in while he talks, then
copy the winners into the selected voice profile. If a voice keeps misbehaving, `DEBUG_SAVE_TTS`
in `config.py` keeps the last 30 spoken clips and their text in
`server/debug/tts/` (git-ignored) so you can listen back.

### Change the model or provider

The brain speaks the OpenAI-style chat API, which OpenRouter, Anthropic, and
OpenAI all serve. Pick one in `config.py`:

| Provider | `LLM_BASE_URL` | `MODEL` example | Key in `.env` |
| --- | --- | --- | --- |
| OpenRouter (default) | `https://openrouter.ai/api/v1` | `anthropic/claude-haiku-4.5` | OpenRouter key |
| Anthropic | `https://api.anthropic.com/v1/` | `claude-haiku-4-5` | Anthropic key |
| OpenAI | `https://api.openai.com/v1` | `gpt-4.1-mini` | OpenAI key |

Whichever you choose, the key goes in `LLM_API_KEY` in `server/.env`. The
model must accept images (Rocky sends camera frames) and tool calls (he
moves his head with them). A small, fast model is the right choice here:
replies are three sentences, and character matters more than reasoning.
Haiku has been the best at staying in character; a few dollars a month
covers a lot of chatting. The project was built and tested through
OpenRouter. Anthropic documents streaming, tool calls, and image input on
its OpenAI-compatible endpoint, which is everything this project uses, but
describes it as a compatibility layer rather than the main road.

### Change how he listens

Also in `config.py`: `VAD_THRESHOLD` (how loud counts as speech),
`TURN_THRESHOLD` and `TURN_MAX_SILENCE` (how sure he needs to be that you
are done, and how long he will wait), `AWAKE_SECONDS` (how long he stays
awake after you speak), `STT_MODEL` (`base.en` is fast; `small.en` hears
better and takes about a second longer), and `MIC_DEVICE` in `.env` if the
computer should use a specific microphone. The console page has sliders for the
listening knobs; changes apply immediately and last until restart.

### Change the body

`firmware/include/config.h` has the pin map, the head's range and speed
limits, servo trims, speaker volume, microphone gain, and camera flips. The
OLED driver line is near the top of `firmware/src/main.cpp` if you use a
different panel. The expressions themselves are drawn in `face.cpp`.

## Troubleshooting

- **The OLED stays black.** SDA and SCL are swapped, or a jumper is loose.
- **The board reboots when the head moves.** The servos are on 3.3 V, or the
  capacitor is missing, or you are on a laptop USB port. Use a 5 V 2 A supply.
- **`wifi: joining` forever.** The network is 5 GHz only, or the antenna is
  not clipped on. Make a 2.4 GHz network or band.
- **The robot prints `brain: connected` then `brain: disconnected, will
  retry` every few seconds.** `ROBOT_TOKEN` differs between `server/.env`
  and `secrets.h`. The server console shows the refusal. If it never gets
  to `brain: connected`, the computer's address changed or the server is
  not running.
- **He never hears you on the computer.** On macOS, check System Settings,
  Privacy & Security, Microphone for your terminal; on Windows, the
  microphone privacy setting for desktop apps. Run `mic` in the server console
  for a level meter. If you have several inputs, set `MIC_DEVICE` in `.env`.
- **"Brain has no key."** `LLM_API_KEY` is empty, or belongs to a different
  provider than `LLM_BASE_URL`.
- **He answers in the computer's voice.** `FISH_AUDIO_API_KEY` is missing
  or the voice ID is wrong. Fine for testing; set it when you want the real
  voice.
- **"cannot speak: no built-in voice on this system."** Linux without
  `espeak-ng`. Install it, or set a Fish key.
- **The voice rattles or sounds muffled.** Use the speaker-tuning sliders on
  the console page, then copy the values into `config.py`.
- **He cuts you off, or waits too long.** Raise `TURN_THRESHOLD` if he jumps
  in early, lower it if he waits. `TURN_MAX_SILENCE` is his patience limit.
- **First start is slow.** It is downloading the speech models. Only once.

## How it works

- **Firmware** (`firmware/src/`): `face.cpp` draws the eyes and mouth at 30
  fps, `servo_neck.cpp` eases the head with speed limits, `camera.cpp`
  keeps the latest JPEG in memory, `mic.cpp` streams 16 kHz audio, and
  `speaker.cpp` plays whatever the brain sends. `link.cpp` is the WebSocket
  client. The USB serial console and the brain drive the same commands.
- **Brain** (`server/brain/`): `ears.py` turns audio into text with
  faster-whisper, using Silero VAD to find speech and Smart Turn
  (`turn.py`) to decide when you have finished. `thinking.py` talks to the
  model, streams the reply sentence by sentence, and gives the model two
  tools: `look` (move the head, take a picture) and `track_face`.
  `mouth.py` turns text into audio with Fish Audio and levels it for the
  small speaker. `tracker.py` follows faces with OpenCV. `eyes.py` serves
  the console page. `main.py` ties it together.
- **Protocol** between the two is in [`docs/protocol.md`](docs/protocol.md):
  JSON commands one way, audio and JPEG frames the other.

Tests run with no hardware and no downloads:

```bash
cd server && python -m unittest tests/test_personality.py tests/test_segmenter.py
```

## Privacy and security

- **Secrets stay in two git-ignored files**: `server/.env` and
  `firmware/include/secrets.h`. Never commit them, and do not share
  `firmware/.pio/` build output either: the compiled binary contains your
  WiFi password.
- **Only your robot can talk to the brain.** The WebSocket port is open on
  your LAN, but the first message must carry `ROBOT_TOKEN`. One robot at a
  time.
- **The camera console is this computer only** and rejects requests from other
  hosts. Opening it to the LAN would let anyone on your WiFi watch the
  camera and read transcripts.
- **Voice is unauthenticated by design.** Anyone in earshot can say "hey
  Rocky". All he can do is move his head and spend a fraction of a cent.
- **What leaves your computer:** each question sends the transcript, the recent
  conversation, your name from `HUMAN_NAME`, and the newest camera frame
  (only for visual questions) to your model provider, and each reply's text
  to Fish Audio if configured. Speech-to-text and face tracking run
  locally. The first run downloads speech models from Hugging Face and
  GitHub, pinned to fixed versions. The console page loads nothing from the
  internet.
- **What is stored:** the in-memory conversation, and nothing else unless
  you turn on `DEBUG_SAVE_TTS` or `DEBUG_SAVE_UTTERANCE` in `config.py`,
  which keep recent spoken replies or the last thing heard in
  `server/debug/` (git-ignored).
- **Known limitation:** robot-to-computer traffic is a plain WebSocket on
  your home network. Someone already on your WiFi who spoofs the computer's address
  could command the robot and receive its streams. Mutual authentication or
  TLS is the fix if that matters to you.

## Credits and license

- Face detection is [YuNet](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet)
  (`server/models/`), Apache 2.0, by Shiqi Yu and the OpenCV Zoo
  contributors.
- Speech detection is [Silero VAD](https://github.com/snakers4/silero-vad)
  (MIT) and end-of-turn detection is
  [Smart Turn](https://github.com/pipecat-ai/smart-turn) (BSD-2-Clause).
  Both download on first run. `server/brain/whisper_features.py` is
  vendored from Smart Turn (Daily, BSD-2-Clause), itself derived from
  HuggingFace transformers (Apache 2.0).
- Rocky and his voice are fan work. *Project Hail Mary* belongs to Andy Weir.

MIT licensed. See [`LICENSE`](LICENSE). Build one, change everything, tell
me what it turned into.

## Virtual Rocky — Windows desktop companion

This working copy adds a hardware-free mode to [cgro00/desk-robot](https://github.com/cgro00/desk-robot), based on commit `34614769c1211fc6943c18bc37ca7ddf850a7cc6`. The original MIT license and firmware remain included. Virtual mode reuses the brain, personality, wake phrases, faster-whisper, Silero, Smart Turn, streaming LLM replies and Fish/built-in speech synthesis.

### Windows setup (PowerShell)

Install **64-bit Python 3.13** from python.org. Open PowerShell in this project's folder:

```powershell
cd server
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements-virtual.txt
```

**ChatGPT Plus/Pro: no API key or `.env` is required.** Launch Rocky, click **Continue with ChatGPT**, sign in to your account in the browser, and approve using your ChatGPT plan. Return to Rocky; he displays **Using ChatGPT plan**. Your Plus plan's usage allowance applies, and is shared with other apps using that plan. Manage usage and access from the face's right-click menu. Sign-in does not give Rocky access to your existing ChatGPT conversations.

The app handles microphone input and Windows speech output locally. Optional webcam images go to the selected ChatGPT model when a question needs vision. ChatGPT plan sign-in supplies the conversational brain, not the ChatGPT app's Voice Mode. No Fish key is required for Windows speech.

The right-click menu includes **ChatGPT accounts**, **ChatGPT model**, **Manage ChatGPT usage**, and **Sign out of ChatGPT**. Available models come from the signed-in account; the first available one is selected initially. You can renew the login with **Continue with ChatGPT**. If you decline plan permission, sign in again and enable it. Quota/connection errors give an actionable message; Rocky does not silently switch to separately billed API usage.

For the original API-key provider instead, create an optional `.env`:

```powershell
Copy-Item .env.example .env
notepad .env
```

Set `LLM_API_KEY`, `LLM_BASE_URL`, and `LLM_MODEL` for an OpenAI-compatible provider. Run `python -m brain.virtual --provider api` (using the environment's Python), or `launch-virtual.cmd --provider api`. `VIRTUAL_LLM_AUTH=api` selects this mode when launching the Python module directly. Physical mode keeps the existing API-key configuration. Never commit `.env`.

Fish Audio is optional: leave `FISH_AUDIO_API_KEY` blank to use Windows' installed System.Speech voice. A failed voice provider falls back to that voice; if speech synthesis or speakers fail, replies remain in the console and the face stays usable. No robot token or ESP32 is needed in virtual mode.

Windows 11: **Settings > Privacy & security > Microphone**, enable microphone access and **Let desktop apps access your microphone**. Repeat under **Camera** if using a webcam. Windows 10 uses **Settings > Privacy > Microphone / Camera**. Choose the desired default input/output in **Settings > System > Sound**. List device names with:

```powershell
.\.venv\Scripts\python.exe -m sounddevice
```

Set `MIC_DEVICE` in `.env` to an input device name if the default is wrong. Prefer a microphone that accepts 16 kHz input. First launch downloads speech/turn models; allow several minutes and keep the console open. Model download failures leave the face and typed-question control available; correct connectivity and restart to retry. Install the Microsoft Visual C++ x64 Redistributable if Windows reports missing native DLLs.

### Launch

From the project root, double-click **launch-virtual.cmd**, or from `server`:

```powershell
.\.venv\Scripts\python.exe -m brain.virtual
```

A 260×180 face appears. Drag it with the left mouse button. Right-click for always-on-top, a typed question, microphone toggle, face tracking toggle, expression previews, and Quit. Say **“hey Rocky”**, wait for his acknowledgment, then ask your question; or say the wake phrase and question together. Follow-up questions work during the existing 60-second awake window. “Go to sleep” returns to wake-phrase-only behavior. The microphone is muted during playback to avoid hearing Rocky's own voice.

```powershell
.\.venv\Scripts\python.exe -m brain.virtual --no-camera
.\.venv\Scripts\python.exe -m brain.virtual --camera 1 --always-on-top
.\.venv\Scripts\python.exe -m brain.virtual --preview
.\.venv\Scripts\python.exe -m brain.virtual --no-mic --no-camera
```

`--preview` draws only the face: no microphone, webcam, speech model downloads or API calls. Camera 0 is the default; try 1 for another connected webcam. An absent or disconnected webcam does not stop conversation. Tracking starts enabled in virtual mode; “stop tracking” / “track me” also control it. Vision questions use a fresh webcam JPEG with an image-capable model. A webcam cannot physically turn, and the `look` tool reports that limitation rather than claiming the camera moved.

The UI opens **no persistent HTTP or WebSocket listener**. Browser sign-in briefly opens a callback on `127.0.0.1`, then closes it on completion/cancel/timeout. Speech recognition runs locally. Questions and relevant webcam images go to the configured LLM provider; Fish TTS sends reply text when configured. This is not fully offline unless the configured services are local. Microphone/model startup and errors are visible in the launcher console. Close the face or select Quit to stop.

### Original physical mode

Continue to run `python -m brain.main` from `server`, with the original firmware and token setup documented above. The physical WebSocket protocol, robot microphone, JPEG camera stream, head movement and PCM speaker behavior remain intact. The shared body boundary is in `brain/body.py`; Qt is imported only by desktop modules, so physical installations do not require PySide6.

### Tests and optional executable

From `server`:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m brain.virtual --smoke-test
```

Tests use fake devices/providers and offscreen Qt; they do not establish real microphone, webcam or paid-provider performance. See `docs/virtual-architecture.md` and `docs/virtual-validation.md` for decisions and verified limitations.

Optional packaging, from the project root after installing virtual requirements:

```powershell
server\.venv\Scripts\python.exe -m pip install pyinstaller
.\build-virtual.cmd
```

Run `server\dist\VirtualRocky\VirtualRocky.exe`. Use **Continue with ChatGPT** for your eligible plan. For API-provider mode, copy `.env.example` to `.env` beside the executable and configure it. Keep the entire distribution folder together. Models still download on first use. This is an initial packaging recipe, not a signed installer; Python mode is the supported first milestone.

## Optional desktop Screen Vision

Install the optional dependencies, then right-click Rocky and choose **Screen
Vision → Enable Screen Vision**. Rocky opens and authenticates a separate visible
helper automatically; no token copying is needed. Use Pause/Resume, Monitor List,
Status, Test, or Disable from the same menu. Desktop access starts disabled, and
closing Rocky or disabling the feature closes its helper. Screenshots are taken
only on demand and may be sent to your configured model provider for screen
questions. See [Screen Vision setup, diagnostics and privacy](docs/screen-vision.md).

**Screen Watch** adds optional local observation every two seconds, lightweight
change detection and at most six recent images in temporary RAM. Watching alone
makes no model requests. Ask “what just happened?” to supply a few relevant old
images plus a fresh current image; static questions use current only. Stop,
Pause or Disable clears the buffer. Active-window/detail crops and resizable face
presets are also available. See [Screen Watch and face details](docs/screen-watch-and-face.md).


## Personalities

Right-click the face -> **Personality** -> select a character. Rocky remains the
initial default. Original starters are Friendly Companion (Nova), Engineer
(Gizmo), Gamer Buddy (Pixel), and Custom Example (Echo). The selected item is checked.
Switching needs no restart: the current spoken turn finishes, old conversation
and temporary visual-source context clear, the face sleeps, and name, wake words,
canned lines and window title update. A configured `default_voice_id` selects that voice on an explicit personality change; the face theme stays selected. Say the new character's wake phrase.
Interrupted network streams may briefly delay switching while they finish closing.
Screen Watch's local buffer stays available. All characters share the existing
emotions, tool availability, Screen Vision privacy controls and visual honesty rules.

Use **Open Personality Folder** to find profiles: `server/personalities/` in source
installs, or `personalities/` beside the executable in packaged builds. Copy
`example.json`, choose a unique ID, edit it, save as UTF-8 JSON, then select
**Reload Personalities**. No Python edits are needed. JSON has no comments or trailing
commas. Reload clears conversation history so edited instructions take effect.
Invalid files are skipped and reported in the console/status. Missing or invalid
selected profiles fall back to Rocky; a built-in recovery copy survives deletion
of Rocky's file. For duplicate IDs the first valid file in filename order wins,
and the duplicate is reported.

Only the active profile ID is saved in the existing UI preferences alongside
window settings (`%LOCALAPPDATA%/VirtualRocky/ui.json`), never in `.env`.
Physical robot brains support these profiles too, without firmware changes.
Local console commands: `personality`, `personality list`, `personality gamer`,
`personality rocky`, `personality reload`, `personality folder`.

| Field | Meaning |
| --- | --- |
| `id` | Required unique lowercase ID; starts with a letter, uses letters/digits/underscore/hyphen, at most 64 characters. |
| `display_name` | Required menu label. |
| `robot_name` | Required name for title, spoken identity and transcription hint. |
| `description` | Optional description. |
| `character_prompt` | Required character/style text; cannot grant tools or override shared honesty/privacy rules. |
| `example_replies` | Optional list of spoken examples with emotion tags. |
| `wake_phrases` | Required nonempty list, including any desired transcription aliases. |
| `canned_lines` | Required nonempty `wake`, `sleep`, `track_on`, `track_off` strings. |
| `voice` | Deprecated legacy field: accepted with a warning and ignored. Use a separate voice profile. |
| `reply_max_sentences` | Optional integer 1-10, default 3; enforced by both providers. |

`{human_name}` in character text/examples/canned lines uses the existing private
HUMAN_NAME setting. `{reply_max_sentences}` in character text uses the profile limit.
The active name updates the speech-recognition hint for each transcription and
name-based sleep commands. Only configured aliases wake the character: Nova won't
wake to "Hey Rocky" unless that alias is explicitly in Nova's profile.

Fish Audio uses the existing `FISH_AUDIO_API_KEY` secret configuration.
**Never store API keys in profile files.** Unknown fields (including credentials)
are rejected. Voice selection, Fish reference IDs, speaker EQ and loudness now belong
to separate voice profiles; see Customizing Your Companion below.

Complete example (copy and change its ID, name, wake phrases and character prompt):

```json
{
  "id": "example",
  "display_name": "Custom Example",
  "robot_name": "Echo",
  "description": "A curious, calm original desktop companion. Speak clear English and help with everyday questions.",
  "character_prompt": "You are Echo. A curious, calm original desktop companion. Speak clear English and help with everyday questions.",
  "example_replies": [
    "[happy] Ready when you are."
  ],
  "wake_phrases": [
    "hey echo",
    "hi echo"
  ],
  "canned_lines": {
    "wake": "What would you like to do?",
    "sleep": "Goodnight. Call my name when you need me.",
    "track_on": "Face tracking on.",
    "track_off": "Face tracking off."
  },
  "reply_max_sentences": 3
}
```

## Customizing Your Companion

Choose three independent layers from the face's right-click menu:

| Layer | Controls | Profile folder |
| --- | --- | --- |
| Personality | Who it is: name, wake phrases, character prompt, examples, canned lines, sentence limit | `server/personalities/` |
| Voice | How it sounds: TTS provider, reference ID, synthesis settings, volume target and EQ | `server/voices/` |
| Face Theme | How it looks: OLED colors and line width | `server/face_themes/` |

For example, choose **Engineer + Rocky Voice + Green OLED**, or **Gamer Buddy (Pixel) + Default System Voice + Purple**. Personalities may declare an optional `default_voice_id`: switching to GLaDOS selects `glados_local`, and switching back to Rocky selects `rocky_voice`. Characters without that field keep the current voice. Manual voice choices remain selected until the personality changes again; reselecting the same personality, reload, restart and ordinary turns do not overwrite them. Themes stay independent. Only personality changes clear conversation history and reset wake state; voices and themes cannot alter prompts, capabilities, or tool safety. All emotions and animations use the same renderer.

Selections restore independently after restart using `active_personality`, `active_voice`, and `active_face_theme` in the existing window preferences. A removed/invalid selected voice falls back to Default System Voice; a missing theme falls back to Classic Cyan; a missing personality falls back to Rocky. Each fallback leaves the other selections alone. First-time migration selects Rocky Voice for saved Rocky identity (including the original default install), and System Voice for other identities. Old personality `voice` fields are accepted with a logged deprecation warning and ignored. Bundled Rocky's existing reference ID now lives in `server/voices/rocky.json`.

Use **Companion Setup…** to see all selections. **Voice → Test Voice** speaks “Voice test. Hello, friend.” through TTS without asking the language model or changing conversation history. System Voice deliberately uses local operating-system speech even if Fish credentials exist. Fish profiles fall back to operating-system speech when credentials or a reference ID are missing, the request fails, or no audio is returned. Missing configuration produces a console warning explaining what is needed; the selected Fish profile remains selected during temporary fallback. A reply snapshots voice settings when it starts; switching takes effect on the next reply without changing current audio.

To customize, use **Open Personality Folder**, **Open Voice Folder**, or **Open Face Theme Folder**. Copy an existing JSON file, give it a unique lowercase `id` and a `display_name`, edit its data, then use the matching **Reload** action. Reload discovers new files and updates active settings. Invalid JSON, duplicate IDs, unknown fields, and out-of-range settings produce warnings in the console; reload status includes presentation-profile warnings. Profiles contain data only, never executable code. Packaged builds keep these folders alongside the executable.

Voice profiles support `provider: "system"`, `"fish"`, or optional `"kokoro_local"` / `"glados_local"` (see local voice setup below), `fish_voice_id` (empty is allowed for the example template), `temperature` and `top_p` (0–1), `level` (0.01–0.4), `highpass_hz` (0–600), and `presence_db` (-12–12). **Do not put API keys into profiles.** Keep `FISH_AUDIO_API_KEY` in the existing secret configuration (`server/.env` for source installs). The example Fish profile has no invented reference ID. Console speaker-tuning controls apply to the active voice until reload/restart; edit its JSON to retain those values.

The existing starter filenames and IDs stay stable: `default.json` (`default`, system speech), `rocky.json` (`rocky_voice`, the existing Fish reference), and `voice_example.json` (`voice_example`, an empty Fish template). To add a Fish voice, copy `voice_example.json`, change its ID and label, supply a reference ID you can use, reload voices, and select it. The `default` ID is reserved for a system-provider fallback; a file that tries to redefine it as Fish is rejected. Even if its file is removed or invalid, a built-in system profile remains available. On Windows this option uses the installed Windows speech engine.

Themes support `background`, `primary`, and `secondary` as `#RRGGBB` colors, plus `line_width` (1–8). Starter themes: Classic Cyan, Green OLED, Amber Terminal, Purple, Blue, and Red / Alert. Geometry, glow, and combined presets are future enhancements; this version keeps shared face geometry and avoids a second source of selection state. Physical robot mode uses personality and voice normally and ignores desktop appearance updates; no firmware change is needed.

Local console commands (no language-model request):

```text
personality list
personality gamer
personality reload
personality folder
voice list
voice rocky_voice
voice reload
voice folder
voice test
theme list
theme purple
theme reload
theme folder
companion status
```

Architecturally, `PersonalityManager` remains the character authority and applies optional voice defaults centrally in `set_active_profile`, only when the identity changes explicitly. It validates the voice identifier and warns while preserving the current voice if the referenced profile is missing. `VoiceManager` and `FaceThemeManager` share a small validated-data loader and use separate preference keys. Providers remain isolated from character prompts; the personality only names a voice profile.

The old voice-selection configuration attributes (`TTS_VOICE_ID`, `TTS_TEMPERATURE`, `TTS_TOP_P`, `TTS_LEVEL`, `TTS_HIGHPASS_HZ`, `TTS_PRESENCE_DB`) have been removed. Python consumers should use `brain.voice_manager.manager.get_active_profile()` or its getters. The live-view HTTP console retains its three legacy slider field names for compatibility, but both their values and updates go directly to VoiceManager. These names hold no separate settings. Global engine controls remain in `config.py`: `TTS_MAX_GAIN` caps gain for every profile, and `TTS_FALLBACK_VOICE` names the macOS built-in voice (Windows/Linux use their OS default). Selecting individual local OS voices through JSON is not implemented yet. Master playback volume belongs to the body/output controls; profile `level` controls synthesis loudness before playback. Personality profiles own none of these values.

## Live Web and Weather

ChatGPT as the model does **not** automatically provide browsing. Web Access is an explicit capability shared by all personalities. Right-click **Web Access** to enable/disable it, inspect status, run **Probe Hosted Search**, configure **Weather Location…**, or open **Last Sources…**. Web Access starts enabled, with hosted search marked unverified until an explicit probe or a changing-information question succeeds. No startup, timer, or background searches run.

Weather uses [Open-Meteo](https://open-meteo.com/en/docs) and [its GeoNames-backed geocoder](https://open-meteo.com/en/docs/geocoding-api), without API credentials for personal/non-commercial use. City/region preferences are optional; no private address is built in. Without a city, “What's the weather?” asks which city to use. “What's the weather in Atlanta?” overrides the default for that turn. Current model-based conditions, humidity, precipitation, wind, and a short high/low/precipitation forecast are returned in Fahrenheit, mph and inches. The combined current/forecast response has a five-minute RAM cache; location lookups and cache entries are bounded. Weather is not automatically saved to long-term memory. Attribution: weather data Open-Meteo (CC BY 4.0); geographic place data GeoNames. Review the service's terms before commercial distribution.

Changing-information questions such as latest news, EVE Online patches, current sports results and explicit web lookups use the Responses `web_search` tool alongside the existing custom namespace. The application verifies a completed search before speaking current claims. Ordinary chat, math, static facts, screen questions and webcam questions do not advertise hosted search. Only one hosted tool call is allowed per answer; no alternate paid search service or API-key provider is silently substituted. The Chat Completions API-provider path currently has no general-search backend, but direct weather works there too.

**Observed connection limitation:** the existing ChatGPT-plan account/model rejected a live hosted-search probe with HTTP 400 during development. Search is therefore not confirmed supported for that connection. The application reports unsupported/error status and says current information cannot be verified, instead of guessing. Use **Probe Hosted Search** after selecting another eligible model/account, or run `python scripts/probe_web_access.py` from `server/` for the same on-demand integration check. Success is remembered in RAM per account/model, not assumed globally. Network/auth/usage failures remain visible. See [official Responses web-search documentation](https://developers.openai.com/api/docs/guides/tools-web-search) and [ChatGPT-plan inference documentation](https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference); generic Responses tool availability does not establish an individual plan token's eligibility.

**Last Sources…** shows recent titles, domains and clickable HTTP(S) URLs; speech omits URLs and citation markers. Sources are replaced for the next relevant weather/search answer. No full-page archive or hosted search output items are retained in conversation history. Structured weather, retrieved memory and private tool payloads are removed after the turn; the user's question and bounded spoken summary remain. The changing-information detector is a conservative local phrase heuristic, not a general fact classifier: explicitly say “search the web” when an unusual request needs live data.

## GLaDOS-Style Companion

Select the personality and optional presentation choices:

- **Personality → GLaDOS** (`server/personalities/glados.json`): clinical, dry scientific sarcasm with original examples. Wake with “hey glados” or “hi glados”. No speculative recognition aliases or copied game quotations are included.
- **Voice → Clinical Synthetic AI** (`server/voices/glados_synthetic.json`): generic local Kokoro `af_heart`, slower delivery, modest EQ and an original subtle `clinical_ai` delay/modulation effect. This does not reproduce a particular actor's vocal identity or use Portal-trained clone weights.
- **Face Theme → Clinical AI** (`server/face_themes/clinical_ai.json`): original pale blue face, dark background and amber accents, using the shared renderer. No logos or copied art.

Switching to GLaDOS now selects **GLaDOS Local** automatically. **Clinical Synthetic AI** remains a manual Kokoro alternative and fallback; choose it after switching if preferred. The face theme stays independent. Shared core honesty, privacy, memory, camera and tool rules take precedence over character style.

To install local speech in a working source environment, run **setup-local-voice.cmd** from the project root. It installs CPU PyTorch from the official PyTorch wheel index, the optional `server/requirements-kokoro.txt` dependencies, and spaCy's English package, then runs `server/scripts/setup_kokoro_voice.py`. These optional dependencies are separate from the normal system/Fish voice install. If the copied `.venv` points to a missing Python installation, rebuild it using the normal setup steps first. Packaged distributions need the optional runtime included at build time and the local model folder beside the executable; the source setup command is intended for source installs.

Model provenance: [official hexgrad/Kokoro-82M repository](https://huggingface.co/hexgrad/Kokoro-82M), v1.0, pinned revision `f3ff3571791e39611d31c381e3a41a3af07b4987`, Apache-2.0 model/voice assets. Runtime library: [hexgrad/kokoro](https://github.com/hexgrad/kokoro), version 0.9.4. The setup downloads only pinned official files into ignored `server/models/tts/kokoro/`; it writes a provenance manifest and verifies every asset before use:

| Asset | Bytes | Verification |
| --- | ---: | --- |
| `kokoro-v1_0.pth` | 327,212,226 | SHA-256 `496dba118d1a58f5f3db2efc88dbdc216e0483fc89fe6e47ee1f2c53f18ad1e4` |
| `voices/af_heart.pt` | 523,425 | SHA-256 `0ab5709b8ffab19bfd849cd11d98f75b60af7733253ad0d67b12382a102cb4ff` |
| `config.json` | 2,351 | Git blob SHA-1 `14a726edd3718279eac426630879ff743955b16a` |

No large assets are committed. The TTS runtime never downloads missing assets or language packages. Missing/broken local dependencies or voice packs produce a warning and use the system voice for that utterance, preserving the selected profile. Kokoro's 24 kHz output is converted into the existing 16 kHz mono PCM pipeline for both bodies. Profile additions: `provider: "kokoro_local"`, `kokoro_voice` (generic American-English pack ID), `speed` (0.7–1.3), and `effect` (`none` or `clinical_ai`). Existing system/Fish profiles keep their behavior.

## GLaDOS Local Voice

This optional GLaDOS-style TTS model runs entirely on your CPU after installation, with no paid TTS service or runtime internet requirement. The existing GLaDOS character prompt is preserved. To install and try it:

1. Ensure the normal project Python environment (`server/.venv`) works; rebuild a copied environment if its original Python installation is missing.
2. Run **setup-glados-voice.cmd** from the project root. It installs the optional pinned `sherpa-onnx==1.13.8` runtime (and its matching core package), then explicitly downloads the official approximately 67 MB compressed package. The ONNX model itself is approximately 61 MB.
3. Right-click the face → **Personality → GLaDOS**. The voice becomes **GLaDOS Local**, provider `glados_local`. Select **Voice → Test Voice**, or type `voice test`. Wake with “hey glados”. Typed questions, normal replies, canned lines and `say` commands share this same speech pipeline.
4. Select **Personality → Rocky** to restore Rocky Voice. A later manual voice choice is respected until the next personality change.

Assets live in ignored `server/models/glados/`: `en_US-glados.onnx`, `tokens.txt` and `espeak-ng-data/`. `server/scripts/setup_glados_voice.py` uses HTTPS with timeouts and a 100 MiB download limit. It extracts into a temporary directory, rejects traversal, absolute paths, Windows alternate streams/reserved names, duplicate paths, links and special files, allowlists expected contents, caps expansion at 256 MiB / 4,000 entries, and validates essential files before installing. An existing valid install skips downloading. An incomplete installation is left intact with instructions to rename its folder and retry. Setup retains upstream attribution files and writes provenance.

The official release asset metadata supplied **no authoritative archive SHA-256** at verification time. Setup records the observed digest for provenance, but does not claim this authenticates the download against an upstream checksum. HTTPS, expected-content validation and extraction restrictions remain enforced; there is no invented checksum.

`brain/glados_local.py` lazily initializes one CPU synthesizer on first speech and serializes access under a lock. Subsequent sentences reuse it. Failed initialization or synthesis warns and tries the existing `glados_synthetic` Kokoro voice, then operating-system TTS. The saved selected voice stays unchanged, and a later utterance can retry after repair. Runtime never downloads or installs anything. The default profile uses natural `speed: 1.0`, `effect: "none"`, and no EQ boost or pitch shifting. Edit `speed` between 0.7 and 1.3 (larger means faster; Sherpa handles inverse VITS length scale), then reload voices.

Sherpa produces 22,050 Hz mono samples, converted through the shared local/WAV conversion into **16,000 Hz mono signed 16-bit little-endian PCM** before existing Equalizer, VoiceEffect, Leveler, debug recording and body transport. Neither Kokoro nor Fish/system speech is removed. Packaged builds need the optional Sherpa runtime and `models/glados/` beside the executable; this setup script targets source installs.

Model source: [sherpa-onnx GLaDOS model documentation](https://k2-fsa.github.io/sherpa/onnx/tts/pretrained_models/vits.html#vits-piper-en-us-glados-english-1-speaker) and [official release package](https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/vits-piper-en_US-glados.tar.bz2), converted from [dnhkng/GLaDOS](https://github.com/dnhkng/GLaDOS), using Piper/VITS. Credits: dnhkng/GLaDOS, [k2-fsa/sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx), and Piper/VITS. Sherpa source is Apache-2.0; dnhkng/GLaDOS source is MIT. These source-code licenses do not automatically settle trained-model rights. The model remains external, downloaded directly during optional setup; no Portal audio or Valve assets are packaged. This project is not affiliated with Valve and does not claim this voice is Ellen McLain.

## Long-Term Memory

**Memory** in the right-click menu provides enable/disable, Known People, Search Memory, Add Memory, Add Person / Aliases, Forget Memory (by fact ID), Status, and **Delete All Memory…** with an explicit confirmation. Data lives in `%LOCALAPPDATA%/VirtualRocky/memory.db`, using SQLite. Database files and model assets are ignored by Git. This is textual memory only; no conversations, images, biometric data, weather or news are archived automatically.

Say **“Remember my friend John likes Factorio.”** to authorize a memory tool, then **“What game does John like?”** to retrieve John's small record. The application checks the direct user's request before allowing model-driven writes or deletions; embedded instructions in screenshots, web results or remembered facts do not authorize writes. Local Add Memory is an explicit save action. A textual introduction may create/retrieve that person's name when a camera session label is assigned. Aliases are simple name metadata and cannot silently collide with another person.

Only up to a handful of relevant facts, selected by normalized words/names/aliases, are included in a model request. The entire database is never uploaded. **Relevant retrieved memory may be sent to the configured ChatGPT or API model to answer your question.** Memories are fallible context; inspect them, forget an incorrect fact and save its correction. Disabling Memory prevents new retrieval/writes without deleting the database. Confirmed Delete All Memory remains available while disabled and removes facts, people and aliases. This first version uses keyword/name retrieval rather than embeddings; it does not infer unstated facts or continually learn from conversation.

## People and Camera

The existing YuNet detector now publishes anonymous face-box tracks to a RAM-only session label manager. No face embeddings, biometric templates, facial fingerprints, crops, image hashes or cross-session matching are created.

With one current face visible, **“This is John.”** can label that anonymous track as John and retrieve John's saved textual facts. With multiple people, the companion asks which person; use **Camera Session People → Label Person…** and select left, center or right. **Visible Tracks…** lists current anonymous IDs and any manually assigned names; **Clear Session Labels** removes associations without deleting textual memory.

Labels survive only unambiguous box continuity within the current camera session. They are dropped on missed detections, ambiguous overlaps, more than two seconds without a fresh update, camera disconnect, tracker stop or application restart. A later visitor at the same location is not matched to a saved face. Reintroduce the person on the next visit. These labels are user assertions, not identity verification; ordinary geometric tracking can still be mistaken during continuous motion. Detector/tracker enablement is required to label a current face. Textual person memory persists independently of camera state.

Local console controls include `web enable`, `web disable`, `web status`, `web sources`, `web probe`, `web location <city, region>`, `memory enable`, `memory disable`, `memory people`, `memory search <query>`, `memory status`, and `people visible` / `people clear`. Save/label actions use the UI or JSON arguments to `memory add`, `memory person`, and `people label`; no extra language-model call is required for local assignment.
