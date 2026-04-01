# TODO

## Voice Settings — Separate client-only from backend

Client-side-only voice settings (like `stt_builtin_enabled`) are currently mixed into the same `voice` object that gets PUT to the backend. The backend ignores unknown fields, so they only persist via a localStorage override hack added in `VoicePanel.tsx`.

**Refactor:** Separate client-only fields from backend fields in `VoicePanel`. Client-only fields should be read/written exclusively from localStorage. Backend fields go through the API. The form should merge both sources on load and save to the right destination on submit.

**Files:** `frontend-react/src/components/Settings/VoicePanel.tsx`

## Whisper STT — WebGPU acceleration

Current Whisper local STT runs on WASM (CPU) which is slow. WebGPU is supported by the browser but `navigator.gpu` is not available inside Web Workers. Options:

1. **Move pipeline to main thread** with `OffscreenCanvas` or chunked processing to avoid blocking UI
2. **Use whisper.cpp compiled to WASM+SIMD** instead of Transformers.js — much faster on CPU (what Handy.computer likely uses)
3. **Wait for browser vendors** to expose WebGPU in workers (Chrome is working on this)

**Files:** `frontend-react/src/workers/whisper.worker.ts`, `frontend-react/src/services/sttService.ts`
