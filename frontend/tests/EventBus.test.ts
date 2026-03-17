import { EventBus } from '../src/utils/EventBus';

describe('EventBus', () => {
  let bus: EventBus;

  beforeEach(() => {
    bus = new EventBus();
  });

  // --- Pub/Sub ---

  test('should subscribe and emit events', () => {
    const handler = jest.fn();
    bus.on('test', handler);
    bus.emit('test', 'hello', 42);
    expect(handler).toHaveBeenCalledWith('hello', 42);
    expect(handler).toHaveBeenCalledTimes(1);
  });

  test('should support multiple handlers for same event', () => {
    const handler1 = jest.fn();
    const handler2 = jest.fn();
    bus.on('test', handler1);
    bus.on('test', handler2);
    bus.emit('test', 'data');
    expect(handler1).toHaveBeenCalledWith('data');
    expect(handler2).toHaveBeenCalledWith('data');
  });

  test('should not call handler for unrelated events', () => {
    const handler = jest.fn();
    bus.on('event-a', handler);
    bus.emit('event-b');
    expect(handler).not.toHaveBeenCalled();
  });

  test('should handle emitting events with no subscribers', () => {
    expect(() => bus.emit('nonexistent')).not.toThrow();
  });

  // --- Unsubscribe ---

  test('should unsubscribe via returned function', () => {
    const handler = jest.fn();
    const unsubscribe = bus.on('test', handler);
    bus.emit('test');
    expect(handler).toHaveBeenCalledTimes(1);

    unsubscribe();
    bus.emit('test');
    expect(handler).toHaveBeenCalledTimes(1); // Not called again
  });

  test('should unsubscribe via off()', () => {
    const handler = jest.fn();
    bus.on('test', handler);
    bus.off('test', handler);
    bus.emit('test');
    expect(handler).not.toHaveBeenCalled();
  });

  // --- Once ---

  test('should fire once handler only once', () => {
    const handler = jest.fn();
    bus.once('test', handler);
    bus.emit('test', 'first');
    bus.emit('test', 'second');
    expect(handler).toHaveBeenCalledTimes(1);
    expect(handler).toHaveBeenCalledWith('first');
  });

  // --- Error Handling ---

  test('should catch handler errors without breaking other handlers', () => {
    const consoleSpy = jest.spyOn(console, 'error').mockImplementation();
    const errorHandler = jest.fn(() => {
      throw new Error('Handler error');
    });
    const normalHandler = jest.fn();

    bus.on('test', errorHandler);
    bus.on('test', normalHandler);
    bus.emit('test');

    expect(errorHandler).toHaveBeenCalled();
    expect(normalHandler).toHaveBeenCalled();
    expect(consoleSpy).toHaveBeenCalled();
    consoleSpy.mockRestore();
  });

  // --- Cleanup ---

  test('should remove all listeners for a specific event', () => {
    const handler1 = jest.fn();
    const handler2 = jest.fn();
    bus.on('test', handler1);
    bus.on('other', handler2);

    bus.removeAllListeners('test');
    bus.emit('test');
    bus.emit('other');

    expect(handler1).not.toHaveBeenCalled();
    expect(handler2).toHaveBeenCalled();
  });

  test('should remove all listeners', () => {
    const handler1 = jest.fn();
    const handler2 = jest.fn();
    bus.on('a', handler1);
    bus.on('b', handler2);

    bus.removeAllListeners();
    bus.emit('a');
    bus.emit('b');

    expect(handler1).not.toHaveBeenCalled();
    expect(handler2).not.toHaveBeenCalled();
  });

  // --- Utility ---

  test('should return correct listener count', () => {
    expect(bus.listenerCount('test')).toBe(0);
    bus.on('test', jest.fn());
    bus.on('test', jest.fn());
    expect(bus.listenerCount('test')).toBe(2);
  });

  test('should return event names', () => {
    bus.on('alpha', jest.fn());
    bus.on('beta', jest.fn());
    expect(bus.eventNames()).toEqual(expect.arrayContaining(['alpha', 'beta']));
  });
});
