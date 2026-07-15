import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  optimizeDeps: {
    include: ["react", "react-dom/client"],
  },
  server: {
    host: "0.0.0.0",
    allowedHosts: ["terminal.local"],
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/gerador": "http://127.0.0.1:8000",
      "/converter": "http://127.0.0.1:8000",
      "/render": "http://127.0.0.1:8000",
      "/map/": "http://127.0.0.1:8000",
      "/projects": "http://127.0.0.1:8000",
      "/s/": "http://127.0.0.1:8000",
    },
    warmup: {
      clientFiles: ["./src/main.tsx"],
    },
  },
  plugins: [react(), tailwindcss()],
});
