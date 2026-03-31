import { useContext } from 'react';
import { ChatContext, type ChatContextValue } from './ChatProvider';

/**
 * Access the ChatService context.
 * Must be used within a <ChatProvider>.
 */
export function useChatService(): ChatContextValue {
  const ctx = useContext(ChatContext);
  if (!ctx) {
    throw new Error('useChatService must be used within a <ChatProvider>');
  }
  return ctx;
}
