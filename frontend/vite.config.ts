import { defineConfig } from 'vitest/config';
import { createLogger } from 'vite';
import react from '@vitejs/plugin-react';

const logger = createLogger();
const defaultError = logger.error.bind(logger);
logger.error = (message, options) => {
  // Proxy messages can contain the request URL and a connection stack. Only a
  // fixed service state belongs in local request logs.
  if (message.includes('http proxy error') || message.includes('ws proxy error')) {
    logger.warn('本地证据 API 暂时不可用。请检查后端是否正在运行。');
  } else {
    defaultError(message, options);
  }
};

export default defineConfig({
  customLogger: logger,
  envDir: false,
  plugins: [react()],
  server: {
    host: '127.0.0.1', port: 5173, strictPort: true,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8766', changeOrigin: false },
      '/health': { target: 'http://127.0.0.1:8766', changeOrigin: false },
    },
  },
  test: { environment: 'jsdom', setupFiles: ['./src/test-setup.ts'], restoreMocks: true },
});
