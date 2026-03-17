# Voxyflow Voice Flow

## Overview

Voice is the **primary input method** in Voxyflow. The system supports two STT engines and integrates seamlessly with the chat pipeline.

## Voice Input Flow

```
User Press (Alt+V or PTT button)
  └→ SttService.startRecording()
       ├→ Mobile: Web Speech API starts
       │    └→ Browser handles recording + STT
       │    └→ Interim results emitted in real-time
       │    └→ Final result emitted on speech end
       └→ Desktop: Whisper WASM (future)
            └→ MediaRecorder captures audio
            └→ Audio chunks collected
            └→ On stop: process through Whisper WASM
            └→ Final result emitted

User Release (Alt+V or PTT button)
  └→ SttService.stopRecording()
       └→ Final transcript emitted

EventBus: VOICE_TRANSCRIPT
  └→ ChatService receives transcript
       └→ If isFinal && not empty:
            └→ chatService.sendMessage(transcript)
                 └→ Message added to AppState
                 └→ Sent via ApiClient WebSocket
                 └→ UI updates via EventBus
```

## STT Engine Selection

```
Device Detection
  ├→ Mobile + Web Speech API available
  │    └→ Use 'webspeech' engine
  │    └→ Leverages native Google/Apple STT
  │    └→ Real-time interim results
  │    └→ No additional model download
  │
  ├→ Desktop + Web Speech API available
  │    └→ Use 'webspeech' (fallback)
  │    └→ Until Whisper WASM is integrated
  │
  └→ Desktop + No Web Speech
       └→ Use 'whisper' engine (placeholder)
       └→ Records audio via MediaRecorder
       └→ Processes through Whisper.cpp WASM
       └→ Higher accuracy, local processing
```

## Web Speech API Details

```typescript
recognition.continuous = true;      // Keep listening
recognition.interimResults = true;  // Show partial results
recognition.lang = 'en-US';        // Configurable
recognition.maxAlternatives = 1;    // Single best result
```

### Error Handling

| Error | User Message |
|-------|-------------|
| `not-allowed` | Microphone access denied |
| `no-speech` | No speech detected |
| `network` | Network error |
| `audio-capture` | No microphone found |

### Auto-restart

When `continuous = true`, the Web Speech API may stop after silence. The `onend` handler auto-restarts if still in recording mode.

## Whisper WASM Integration (Planned)

### Architecture

```
Audio Input → MediaRecorder → WebM Blob
  → Float32 PCM conversion
  → Whisper.cpp WASM module
  → Transcript text
  → EventBus emission
```

### Advantages

- **Privacy** — All processing local, no cloud STT
- **Accuracy** — Whisper models are state-of-the-art
- **Languages** — Multi-language support built in
- **Offline** — Works without internet

### Requirements

- WASM support in browser
- ~40MB model download (small model)
- Web Workers for non-blocking processing

## Audio Output Flow

```
Backend Response (with audio)
  └→ ApiClient receives message
       └→ ChatService processes response
            └→ If audio buffer present:
                 └→ AudioService.playAudio(buffer)
                      └→ AudioContext decodes
                      └→ BufferSource plays through GainNode
                      └→ Volume controlled by AppState
```

### Audio Queue

Multiple audio segments can be queued:

```
AudioService.queueAudio(buffer1)
AudioService.queueAudio(buffer2)
  └→ Plays buffer1
  └→ On end: plays buffer2
  └→ On end: queue empty
```

## UI Indicators

### Recording State

- **PTT Button** — Red + pulsing when recording
- **Recording Dot** — Red dot with "Recording..." label
- **Top Bar** — Voice indicator shows "Listening..."
- **Transcript** — Real-time display below button

### Keyboard Shortcut

`Alt+V` — Toggle recording on/off

- First press: start recording
- Second press: stop recording
- Works from anywhere in the app

## Configuration

```typescript
// SttService
sttService.setLanguage('fr-FR');  // Change language

// AudioService
audioService.volume = 0.5;        // Set volume (0-1)
audioService.stop();              // Stop all playback
audioService.clearQueue();        // Clear pending audio
```
