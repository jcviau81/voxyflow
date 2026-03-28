# Voxyflow Voice Flow

## Overview

Voice is the **primary input method** in Voxyflow. The system supports multiple STT engines, wake word detection, and integrates seamlessly with the chat pipeline.

## Voice Modes

### 1. Push-to-Talk (PTT)
- **Desktop:** Hold mouse button or Alt+V to record, release to stop
- **Mobile:** Tap to start, tap to stop (toggle mode)
- Transcript sent immediately on stop

### 2. Wake Word Mode
- Say "Voxy" → wake word detected (Silero/Alexa ONNX, client-side)
- Ack sound plays → mic opens in **continuous recording mode**
- Speak naturally with pauses — no rush
- **Debounce timer (3s)** resets on every transcript update (interim or final)
- After 3s of silence → message auto-sent → wake word listening resumes

## Wake Word Flow (Current Implementation)

```
WakeWordService (ONNX VAD model, always listening)
  └→ Detects "Voxy" keyword
       └→ Stops wake word listener (releases mic)
       └→ Plays ack sound ("ding")
       └→ VoiceInput starts SttService.startRecording() [continuous mode]
            └→ Web Speech API with continuous=true (desktop)
            └→ Web Speech API with continuous=false + auto-restart (mobile)
            └→ Transcript events emitted via EventBus

VoiceInput receives VOICE_TRANSCRIPT events:
  └→ On ANY transcript update (interim or final):
       └→ Reset 3s debounce timer
  └→ On isFinal:
       └→ Update autoSendBuffer with full transcript
       └→ Reset 3s debounce timer
  └→ Timer expires (3s no speech):
       └→ autoSendMessage() → chatService.sendMessage()
       └→ Stop recording, clear buffers
       └→ Restart wake word listener
```

### Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| **Continuous mode** (not oneShot) | OneShot mode cuts on browser's endpointing which is too aggressive — users can't pause to breathe |
| **3s debounce on all transcript events** | Resets timer even on interim results, so pauses < 3s don't trigger send |
| **No Web Speech API endpointing** | Browser decides "speech ended" too fast. We ignore it and use our own timer |
| **80 oneShot retries at 200ms** (fallback) | If oneShot is ever used, retries keep mic alive during pauses |

### Tuning Parameters

| Parameter | Location | Default | Purpose |
|-----------|----------|---------|---------|
| `WAKE_WORD_SEND_DELAY_MS` | VoiceInput.ts | 3000ms | Silence duration before auto-send |
| `MAX_ONESHOT_RETRIES` | SttService.ts | 80 | Max retries in oneShot mode (fallback) |
| `SILENCE_TIMEOUT_MS` | SttService.ts | 5000ms | Silence timeout for oneShot backup |

## PTT Flow

```
User Press (Alt+V or PTT button)
  └→ SttService.startRecording()
       ├→ Web Speech API: continuous + interimResults
       └→ Whisper WASM: MediaStream → AudioContext → Worker

User Release
  └→ SttService.stopRecording()
       └→ Final transcript emitted → sent as message
```

## STT Engine Selection

| Engine | When | Privacy | Quality |
|--------|------|---------|---------|
| `webspeech` | Default, requires internet | Audio sent to Google | Good, real-time |
| `whisper_local` | Settings → Voice → Whisper WASM | 100% client-side | Excellent, slight delay |

### Web Speech API Behavior

```typescript
// Desktop: continuous mode, auto-restarts on end
recognition.continuous = true;
recognition.interimResults = true;

// Mobile: non-continuous (Android Chrome limitation), manual restart loop
recognition.continuous = false;
// onend → 250ms delay → restart (avoids crash loops)
```

### Whisper WASM

- Runs in WebWorker (non-blocking)
- Models: tiny (~40MB) to medium (~750MB)
- Audio collected via ScriptProcessorNode → Float32Array → Worker
- Single transcription on stop (not streaming)

## Audio Output (TTS)

```
Backend response with text
  └→ TtsService.speak(text) → POST /api/settings/tts/speak
       └→ Backend → XTTS v2 server (localhost:5500)
       └→ Audio WAV returned → played in browser
       └→ On TTS complete → wake word listener restarts
```

## Error Handling

| Error | Behavior |
|-------|----------|
| `not-allowed` | Show "Microphone access denied" |
| `no-speech` | Mobile: ignore (transient). Desktop: show error |
| `network` | Suggest switching to Whisper WASM |
| `audio-capture` | Show "No microphone found" |

## Configuration

Configured via Settings UI → Voice tab:
- STT engine (Native / Whisper WASM)
- Language (auto / en / fr)
- TTS on/off, auto-play, volume
- Wake word on/off
- Auto-send toggle

---

*Last updated: 2026-03-27 — Wake word continuous mode, debounce auto-send*
