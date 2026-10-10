> Historical working notes from 2026-09-07, kept for reference. Line numbers
> and some file names have drifted since; the current mic settings are in
> `server/brain/config.py` and the README's troubleshooting section.

# Rocky microphone investigation — 2026-09-07

Software tuning is worth testing before replacing the microphone. The review
found several plausible causes, but no fresh recording of a failed interaction
was available to identify which one is responsible. No firmware, server settings,
or running behavior were changed during this investigation.

## Evidence collected

- Live `/status` confirmed the robot was connected, listening through `robot`,
  asleep, and not speaking. VAD threshold was 0.5. One idle snapshot had RMS
  0.00112 and speech probability 0.00014; this is not a measurement of speech
  sensitivity or a representative noise-floor survey.
- Capture uses GPIO42 clock / GPIO41 data, PDM receive on I2S0, 16 kHz mono,
  16-bit PCM. The pins and audio format agree with
  [Seeed's microphone example](https://wiki.seeedstudio.com/xiao_esp32s3_sense_mic/).
- Firmware applies fixed 6x gain and clamps samples to int16 in
  `firmware/src/mic.cpp:52`; the custom 120 Hz high-pass filter runs afterward,
  on the server. Raising gain can amplify noise and clip peaks before this
  server filter can help. Actual clipping has not been measured.
- `server/debug/last_utterance.wav` is from September 5. It contains 1.56 seconds
  at 16 kHz, RMS 0.1043, peak 0.9000, and no samples at full scale. The recording
  is saved after filtering and normalization, so these numbers cannot rule out
  earlier clipping or establish today's incoming microphone level. Its source
  microphone is not recorded.
- Replaying that saved file through the cached Silero model at decreasing
  amplitudes classified 22/48 frames as speech at its saved level, 20/48 at
  0.1x, and 15/48 at 0.02x, using threshold 0.5. All versions still reached high
  peak speech probability. This demonstrates amplitude can affect speech
  boundaries; it does not reproduce the user's missed interaction.

## Improvements to evaluate, in order

1. **Measure an actual miss and try a more sensitive detector.** In the live
   console, compare "Hears speech above" at 0.5, 0.4, then 0.35 using the same
   phrases at the usual seating distance. These are trial values, not calibrated
   recommendations. Count missed wake phrases, wrong words, premature replies,
   and false triggers during room noise. Changes already work without flashing
   and reset on server restart. If speech probability stays near zero, reducing
   the threshold a little is unlikely to solve the underlying problem.

2. **Use a lower threshold to continue speech than to start it.** The custom
   segmenter in `server/brain/ears.py:129` currently uses 0.5 for both. Softer
   syllables can count as silence and trigger Smart Turn evaluation after about
   0.2 seconds; Smart Turn may still decide to wait. Silero's
   [reference implementation](https://github.com/snakers4/silero-vad/blob/master/src/silero_vad/utils_vad.py)
   defaults its silence threshold to the start threshold minus 0.15. Adopting
   this behavior is a targeted way to preserve quiet speech within a sentence.

3. **Improve level handling only after checking raw peaks and noise.** The
   server boosts completed turns before transcription (`ears.py:353`), but
   this is too late to help speech rejected by the first detector. A bounded
   level controller before detection could help low-level speech; it must avoid
   continually boosting room noise. Measure incoming peak, RMS, clipping,
   and the effect of servo movement. If the firmware's 6x gain clips, reduce it
   or remove residual DC/rumble before amplification. Software gain alone cannot
   improve the ratio of speech to background noise.

4. **Compare transcription settings if Rocky detects speech but gets words
   wrong.** Current settings are `base.en` and `beam_size=1`. Compare `small.en`
   and a larger beam on identical recorded phrases, measuring accuracy and
   response time on this Mac. Whisper documents its
   [model size / speed tradeoffs](https://github.com/openai/whisper#available-models-and-languages).
   Also test the second VAD pass: `Transcriber.transcribe()` sets
   `vad_filter=True`, using faster-whisper's own threshold independently of the
   live sensitivity slider. Compare disabling it for already segmented turns
   or aligning its threshold, checking false transcriptions as well as misses.
   [faster-whisper documents this additional filter](https://github.com/SYSTRAN/faster-whisper#vad-filter).

5. **Check placement and interference.** Compare the usual position with the
   microphone closer to the speaker, its acoustic opening unobstructed, and
   head tracking disabled. Improvement with proximity or still servos would
   motivate placement or mechanical isolation changes. No evidence yet
   establishes a need for a new microphone.

## Separate limitations

- Rocky discards incoming mic audio while his reply plays
  (`server/brain/main.py:441`). Speaking over him will be missed by design.
  Echo cancellation would be a separate feature requiring a synchronized
  playback reference and testing, not a gain adjustment. Espressif provides
  [an audio front end with AEC, noise suppression, and AGC](https://docs.espressif.com/projects/esp-sr/en/latest/esp32s3/audio_front_end/README.html),
  but integrating it into this Arduino project is additional engineering work.
- Audio and camera frames share the WebSocket. The firmware has a 16-frame
  microphone queue (480 ms) and drops old audio if it fills. There are no drop
  counters or sequence numbers to establish whether this occurs in normal use.
  Add telemetry if misses correlate with Wi-Fi trouble or camera activity;
  packet loss is not established by this review.
- Current saved-utterance debugging captures only turns that pass segmentation,
  after normalization. A short diagnostic capture before segmentation is needed
  to inspect speech that Rocky fails to detect at all.

## Follow-up implementation

The default `VAD_THRESHOLD` is now 0.4. The segmenter continues an existing
speech turn down to `max(0.01, VAD_THRESHOLD - 0.15)`, or 0.25 at the new default.
Both thresholds follow live console sensitivity changes. Firmware gain and
transcription settings remain as investigated above.

Three automated regression tests cover soft speech continuation without false
starts, actual silence ending a turn, runtime sensitivity changes, and the
minimum console threshold. Run them from `server/` with
`.venv/bin/python -m unittest discover -s tests -v`.

Fresh speech at the user's normal distance is still needed to assess practical
improvement and false triggers. Use raw audio to decide whether gain, filtering,
transcription, or hardware needs attention next.
