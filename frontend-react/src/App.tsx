import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { WebSocketProvider } from './providers/WebSocketProvider';

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
        <h1>Hello Voxyflow</h1>
      </WebSocketProvider>
    </QueryClientProvider>
  );
}

export default App;
