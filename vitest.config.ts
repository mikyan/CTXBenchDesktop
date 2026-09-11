import { defineConfig, mergeConfig } from 'vitest/config';
import viteConfig from './vite.config.ts';

export default mergeConfig(viteConfig, defineConfig({
  test: {
    // Benchmark repositories are untrusted inputs and often intentionally fail.
    // Never discover/execute their tests as part of the desktop's own test suite.
    include: ['src/**/*.{test,spec}.?(c|m)[jt]s?(x)'],
  },
}));
