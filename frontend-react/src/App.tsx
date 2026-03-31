import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { RouterProvider } from 'react-router-dom';
import { WebSocketProvider } from './providers/WebSocketProvider';
import { ChatProvider } from './contexts/ChatProvider';
import { Toaster } from './components/ui/Toaster';
import { router } from './router';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 2,
      refetchOnWindowFocus: false,
    },
  },
});

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <WebSocketProvider>
        <ChatProvider>
          <RouterProvider router={router} />
          <Toaster />
        </ChatProvider>
      </WebSocketProvider>
    </QueryClientProvider>
  );
}

export default App;
