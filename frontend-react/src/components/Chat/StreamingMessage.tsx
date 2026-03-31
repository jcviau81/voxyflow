import { memo } from 'react';
import { MessageBubble } from './MessageBubble';
import type { Message } from '../../types';

/**
 * StreamingMessage — thin wrapper around MessageBubble for a live-streaming message.
 *
 * The actual streaming state (content updates) lives in useMessageStore and is
 * driven by ChatProvider's handleStreamingChunk. This component just renders the
 * current snapshot with a streaming cursor, and removes the cursor once streaming ends.
 *
 * Kept as a separate named export so MessageList can label streamed messages in the
 * virtual list and potentially apply different animations.
 */
export const StreamingMessage = memo(function StreamingMessage({
  message,
}: {
  message: Message;
}) {
  // MessageBubble already handles the streaming cursor and live content;
  // this wrapper exists for semantic clarity and potential future differentiation
  // (e.g. scroll-lock behaviour, typing indicator overlay).
  return <MessageBubble message={message} />;
});
