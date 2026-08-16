import { defineConfig } from 'vitest/config';

// Scoped to pure-logic modules only (risk/engine.ts has no Workers-runtime
// imports). Routes and index.ts touch Fetcher/Cloudflare bindings and need
// @cloudflare/vitest-pool-workers to run for real — not set up here yet;
// this config intentionally stays narrow rather than half-configuring that.
export default defineConfig({
  test: {
    include: ['src/**/*.test.ts'],
  },
});
