import { defineConfig } from '@playwright/test';

// The runner always starts a disposable Java service. Never point checks at user data.
if (!process.env.DOCTRAIL_E2E_URL || !process.env.DOCTRAIL_E2E_OUTPUT) {
  throw new Error('Use npm run test:e2e to start the isolated Java service.');
}
export default defineConfig({
  testDir: './tests',
  timeout: 45_000,
  expect: { timeout: 8000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  forbidOnly: Boolean(process.env.CI),
  outputDir: `${process.env.DOCTRAIL_E2E_OUTPUT}/results`,
  reporter: [['list'], ['json', { outputFile: `${process.env.DOCTRAIL_E2E_OUTPUT}/report.json` }]],
  use: {
    baseURL: process.env.DOCTRAIL_E2E_URL,
    browserName: 'chromium',
    viewport: { width: 1440, height: 1000 },
    locale: 'ko-KR',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
});
