/** Voice / STT event name constants — shared by services and components */

export const VOICE_EVENTS = {
  VOICE_START: 'voice:start',
  VOICE_STOP: 'voice:stop',
  VOICE_TRANSCRIPT: 'voice:transcript',
  VOICE_ERROR: 'voice:error',
  VOICE_MESSAGE_SENT: 'voice:message:sent',
  WAKEWORD_DETECTED: 'wakeword:detected',
  WAKEWORD_ERROR: 'wakeword:error',
  TOAST_SHOW: 'ui:toast:show',
  VOICE_BUFFER_UPDATE: 'voice:buffer-update',
  VOICE_RECORDING_STOP: 'voice:recording-stop',
} as const;

export const STT_EVENTS = {
  TRANSCRIBING: 'stt:transcribing',
  TRANSCRIBE_DONE: 'stt:transcribe_done',
  MODEL_STATUS: 'stt:model_status',
  MODEL_PROGRESS: 'stt:model_progress',
} as const;

export interface SttResult {
  transcript: string;
  confidence: number;
  isFinal: boolean;
}
