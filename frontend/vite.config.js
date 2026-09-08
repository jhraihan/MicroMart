import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'node:path'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, import.meta.dirname, '')
  // Django's default is 8000, but that port is not always free. Override with
  // VITE_BACKEND_ORIGIN in .env.local rather than editing this file.
  const backend = env.VITE_BACKEND_ORIGIN || 'http://127.0.0.1:8000'

  return {
  plugins: [react(), tailwindcss()],
  // Vitest transforms with esbuild and does not inherit the React plugin's
  // JSX handling, so without this every .jsx test fails with "React is not
  // defined". The build prints a notice that it ignores this in favour of
  // oxc, which is fine -- the React plugin already handles JSX there.
  esbuild: { jsx: 'automatic' },
  resolve: {
    alias: { '@': path.resolve(import.meta.dirname, 'src') },
  },
  server: {
    port: 5173,
    // Proxying /api in dev keeps the browser same-origin, so the HttpOnly
    // refresh cookie behaves exactly as it will behind Nginx in production.
    proxy: {
      '/api': { target: backend, changeOrigin: true },
      '/media': { target: backend, changeOrigin: true },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.js'],
    css: false,
    exclude: ['e2e/**', 'node_modules/**'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'html'],
      include: ['src/**/*.{js,jsx}'],
    },
  },
  build: {
    rollupOptions: {
      output: {
        /*
         * The admin bundle is code-split so shoppers never download it
         * (PRD §8.3). Vendor chunks are split to keep the storefront entry
         * inside its performance budget.
         *
         * Only React and the router are named here, and both are matched on
         * the package directory rather than by substring. Two rules learned
         * the hard way, both verifiable in the build output:
         *
         * 1. `id.includes('react')` also matches `react-redux`, `react-is`
         *    and `react-smooth` -- Recharts' own dependencies -- and pulls
         *    them into the eagerly loaded React chunk.
         * 2. **Recharts must not be given a manual chunk name.** Rolldown
         *    merges manual groups that share a module, so a `charts` group
         *    (which depends on React) swallows the `react` group and the
         *    merged chunk lands in the entry's static graph: index.html then
         *    modulepreloads ~490 kB of charting for every shopper. Left
         *    unnamed, Recharts is reachable only through the lazy admin
         *    overview import and rolldown keeps it in that async chunk, which
         *    is exactly where it belongs.
         */
        manualChunks(id) {
          if (!id.includes('node_modules')) return
          if (/node_modules\/react-router(-dom)?\//.test(id)) return 'router'
          if (/node_modules\/(react|react-dom|scheduler)\//.test(id)) return 'react'
        },
      },
    },
  },
  }
})
