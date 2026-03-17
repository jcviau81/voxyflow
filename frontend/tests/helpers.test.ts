import { createElement, generateId, markdownToHtml, escapeHtml, formatTime, debounce, truncate, cn, isMobile, deepClone } from '../src/utils/helpers';

describe('helpers', () => {
  // --- createElement ---

  describe('createElement', () => {
    test('should create an element with tag', () => {
      const el = createElement('div');
      expect(el.tagName).toBe('DIV');
    });

    test('should set attributes', () => {
      const el = createElement('div', { className: 'test', id: 'myid' });
      expect(el.className).toBe('test');
      expect(el.id).toBe('myid');
    });

    test('should set data attributes', () => {
      const el = createElement('div', { 'data-id': '123' });
      expect(el.getAttribute('data-id')).toBe('123');
    });

    test('should append string children', () => {
      const el = createElement('span', {}, 'Hello', ' World');
      expect(el.textContent).toBe('Hello World');
    });

    test('should append node children', () => {
      const child = document.createElement('b');
      child.textContent = 'bold';
      const el = createElement('div', {}, child);
      expect(el.querySelector('b')).toBeTruthy();
      expect(el.textContent).toBe('bold');
    });

    test('should create without attributes', () => {
      const el = createElement('p', undefined, 'text');
      expect(el.tagName).toBe('P');
      expect(el.textContent).toBe('text');
    });
  });

  // --- generateId ---

  describe('generateId', () => {
    test('should generate unique IDs', () => {
      const ids = new Set(Array.from({ length: 100 }, () => generateId()));
      expect(ids.size).toBe(100);
    });

    test('should return string', () => {
      expect(typeof generateId()).toBe('string');
    });
  });

  // --- markdownToHtml ---

  describe('markdownToHtml', () => {
    test('should convert bold text', () => {
      expect(markdownToHtml('**bold**')).toContain('<strong>bold</strong>');
    });

    test('should convert italic text', () => {
      expect(markdownToHtml('*italic*')).toContain('<em>italic</em>');
    });

    test('should convert inline code', () => {
      expect(markdownToHtml('use `code` here')).toContain('<code>code</code>');
    });

    test('should convert headers', () => {
      expect(markdownToHtml('# Title')).toContain('<h1>Title</h1>');
      expect(markdownToHtml('## Sub')).toContain('<h2>Sub</h2>');
      expect(markdownToHtml('### H3')).toContain('<h3>H3</h3>');
    });

    test('should convert links', () => {
      const result = markdownToHtml('[Google](https://google.com)');
      expect(result).toContain('href="https://google.com"');
      expect(result).toContain('>Google</a>');
    });

    test('should escape HTML in input', () => {
      const result = markdownToHtml('<script>alert("xss")</script>');
      expect(result).not.toContain('<script>');
      expect(result).toContain('&lt;script&gt;');
    });
  });

  // --- escapeHtml ---

  describe('escapeHtml', () => {
    test('should escape all HTML entities', () => {
      expect(escapeHtml('&<>"\'')).toBe('&amp;&lt;&gt;&quot;&#039;');
    });

    test('should pass through safe text', () => {
      expect(escapeHtml('Hello World')).toBe('Hello World');
    });
  });

  // --- formatTime ---

  describe('formatTime', () => {
    test('should format today timestamps', () => {
      const now = Date.now();
      const result = formatTime(now);
      expect(result).toMatch(/\d{1,2}:\d{2}/);
    });

    test('should format yesterday timestamps', () => {
      const yesterday = Date.now() - 86400000;
      const result = formatTime(yesterday);
      expect(result).toContain('Yesterday');
    });
  });

  // --- debounce ---

  describe('debounce', () => {
    jest.useFakeTimers();

    test('should debounce function calls', () => {
      const fn = jest.fn();
      const debounced = debounce(fn, 100);

      debounced();
      debounced();
      debounced();

      expect(fn).not.toHaveBeenCalled();
      jest.advanceTimersByTime(100);
      expect(fn).toHaveBeenCalledTimes(1);
    });

    afterAll(() => {
      jest.useRealTimers();
    });
  });

  // --- truncate ---

  describe('truncate', () => {
    test('should truncate long strings', () => {
      expect(truncate('Hello World', 8)).toBe('Hello...');
    });

    test('should not truncate short strings', () => {
      expect(truncate('Hi', 10)).toBe('Hi');
    });
  });

  // --- cn ---

  describe('cn', () => {
    test('should join class names', () => {
      expect(cn('a', 'b', 'c')).toBe('a b c');
    });

    test('should filter falsy values', () => {
      expect(cn('a', false, null, undefined, 'b')).toBe('a b');
    });
  });

  // --- deepClone ---

  describe('deepClone', () => {
    test('should deep clone objects', () => {
      const obj = { a: 1, b: { c: 2 } };
      const clone = deepClone(obj);
      clone.b.c = 99;
      expect(obj.b.c).toBe(2);
    });
  });

  // --- isMobile ---

  describe('isMobile', () => {
    test('should return boolean', () => {
      expect(typeof isMobile()).toBe('boolean');
    });
  });
});
