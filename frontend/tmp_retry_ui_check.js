const { chromium } = require('playwright');

(async () => {
  const alertsResp = await fetch('http://localhost:8000/api/alerts?limit=100');
  const alertsData = await alertsResp.json();
  const candidate = (alertsData.alerts || []).find(
    (a) => !a.retry_in_progress && !!a.sop_workflow_id
  );
  if (!candidate) {
    throw new Error('No eligible alert found with retry_in_progress=false and sop_workflow_id present');
  }
  const alertId = candidate._id;
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  await page.goto('http://localhost:3001', { waitUntil: 'networkidle' });
  await page.getByRole('button', { name: 'Retry' }).click();
  await page.waitForSelector('h1:has-text("Retry Alerts")', { timeout: 15000 });

  await page.getByRole('button', { name: 'Filters' }).click();
  await page.locator('input[placeholder="Alert ID"]').fill(alertId);
  await page.getByRole('button', { name: 'Apply' }).click();

  const row = page.locator('label').filter({ hasText: alertId }).first();
  await row.waitFor({ timeout: 15000 });
  await row.locator('input[type="checkbox"]').check();
  await page.locator('section:has-text("Run Retry") select').first().selectOption('level2');
  await page.getByRole('button', { name: 'Run Retry' }).click();

  await row.getByRole('button', { name: 'History' }).click();

  const apiBase = 'http://localhost:8000';
  let state = 'queued';
  let batchId = null;
  for (let i = 0; i < 25; i++) {
    const res = await fetch(`${apiBase}/api/alerts/${alertId}/retries`);
    const body = await res.json();
    const first = (body.retries || [])[0];
    if (first) {
      state = first.state || 'unknown';
      batchId = first.batch_id || null;
      if (state !== 'queued') break;
    }
    await new Promise(r => setTimeout(r, 1000));
  }

  console.log(JSON.stringify({ alertId, batchId, state }, null, 2));
  await browser.close();
})();
