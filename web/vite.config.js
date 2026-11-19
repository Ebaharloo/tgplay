import { defineConfig } from 'vite'

// No plugin-react: Vite's built-in JSX transform is enough for `npm run build`
// and keeps this app on the single shared ~/node_modules copy.
export default defineConfig({
  server: { port: 5173, proxy: { '/api': 'http://127.0.0.1:8799' } },
  build: { outDir: 'dist', emptyOutDir: true },
})
