import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { resolve } from 'path';

export default defineConfig({
  plugins: [react()],
  build: {
    chunkSizeWarningLimit: 1200,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes('node_modules')) return undefined;
          if (id.includes('/react/') || id.includes('/react-dom/')) {
            return 'react-vendor';
          }
          if (id.includes('/@antv') || id.includes('/@ant-design/charts')) {
            return 'charts-vendor';
          }
          if (
            id.includes('/antd/')
            || id.includes('/@ant-design/icons')
            || id.includes('/rc-')
            || id.includes('/@rc-component/')
          ) {
            return 'ui-vendor';
          }
          if (id.includes('/axios') || id.includes('/zustand') || id.includes('/immer') || id.includes('/dayjs')) {
            return 'app-vendor';
          }
          return undefined;
        },
      },
    },
  },
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
    },
  },
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true,
      },
    },
  },
});
