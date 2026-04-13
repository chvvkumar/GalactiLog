import { defineConfig } from "vite";
import solidPlugin from "vite-plugin-solid";

export default defineConfig({
  plugins: [solidPlugin()],
  server: {
    port: 3000,
    proxy: {
      "/api": "http://localhost:8080",
      "/thumbnails": "http://localhost:8080",
    },
  },
  build: {
    target: "esnext",
    rollupOptions: {
      output: {
        manualChunks: {
          'chart-vendor': ['chart.js', '@kurkle/color', 'chartjs-adapter-date-fns', 'chartjs-plugin-annotation'],
          'solid-vendor': ['solid-js', '@solidjs/router'],
        },
      },
    },
  },
});
