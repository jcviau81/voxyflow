import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { RouterProvider } from 'react-router-dom';
import { WebSocketProvider } from './providers/WebSocketProvider';
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
        <RouterProvider router={router} />
      </WebSocketProvider>
    </QueryClientProvider>
  );
}

export default App;
