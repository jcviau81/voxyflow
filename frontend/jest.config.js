/** @type {import('ts-jest').JestConfigWithTsJest} */
module.exports = {
  preset: 'ts-jest',
  testEnvironment: 'jsdom',
  roots: ['<rootDir>/tests'],
  testMatch: ['**/*.test.ts'],
  moduleNameMapper: {
    '^@/(.*)$': '<rootDir>/src/$1',
    '\\.css$': '<rootDir>/tests/__mocks__/styleMock.js',
  },
  transform: {
    '^.+\\.ts$': ['ts-jest', {
      tsconfig: {
        module: 'commonjs',
        moduleResolution: 'node',
        target: 'ES2020',
        lib: ['ES2020', 'DOM', 'DOM.Iterable'],
        strict: true,
        esModuleInterop: true,
        skipLibCheck: true,
        isolatedModules: true,
        types: ['jest'],
      },
    }],
  },
  collectCoverageFrom: [
    'src/**/*.ts',
    '!src/main.ts',
    '!src/types/**',
    '!src/**/index.ts',
  ],
  coverageDirectory: 'coverage',
  coverageReporters: ['text', 'text-summary', 'lcov'],
  coverageThresholds: {
    global: {
      branches: 50,
      functions: 50,
      lines: 50,
      statements: 50,
    },
  },
  setupFiles: [],
  verbose: true,
};
