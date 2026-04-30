import { test, expect } from "@playwright/test";

const API_BASE = "http://localhost:8000";

async function getAlertsList(request: any, limit = 1) {
  const resp = await request.get(`${API_BASE}/api/alerts?limit=${limit}`);
  const data = await resp.json();
  return Array.isArray(data) ? data : data.alerts || [];
}

test("home page loads with tabs and alert list", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator("button:has-text('Alert Analysis')")).toBeVisible();
  await expect(page.locator("button:has-text('Retry')")).toBeVisible();
  await expect(page.locator("button:has-text('SOP Management')")).toBeVisible();
  await expect(page.locator("h1")).toContainText("Alerts");
});

test("Retry tab renders and shows run controls", async ({ page }) => {
  await page.goto("/");
  await page.click("button:has-text('Retry')");

  await expect(page.locator("h1:has-text('Retry Alerts')")).toBeVisible({ timeout: 5000 });
  await expect(page.locator("h2:has-text('Run Retry')")).toBeVisible();
  await expect(page.locator("text=Level 1 (Re-ingest alert)")).toBeVisible();
  await expect(page.locator("button:has-text('Run Retry')")).toBeVisible();
  await expect(page.locator("h2:has-text('Alert Retry History')")).toBeVisible();
});

test("alert detail page loads via URL", async ({ page }) => {
  const alerts = await getAlertsList(page.request);
  if (alerts.length === 0) {
    test.skip();
    return;
  }
  const alertId = alerts[0]._id;

  await page.goto(`/alerts?id=${alertId}`);
  await expect(page.locator("h1")).toContainText("Alert Details");
  await expect(page.locator("span.text-\\[\\#888888\\]:has-text('Application')").first()).toBeVisible();
  await expect(page.locator("span.text-\\[\\#888888\\]:has-text('Severity')").first()).toBeVisible();
});

test("SOP Management tab renders", async ({ page }) => {
  await page.goto("/");
  await page.click("button:has-text('SOP Management')");
  await expect(page.locator("text=SOP Management")).toBeVisible({ timeout: 5000 });
});

test("SOP Management classifier section shows dynamic classifiers", async ({ page }) => {
  await page.goto("/");
  await page.click("button:has-text('SOP Management')");
  await expect(page.locator("text=SOP Management")).toBeVisible({ timeout: 5000 });

  // Click the first SOP in the list if any are available
  const sopItems = page.locator("[class*='cursor-pointer']");
  const count = await sopItems.count();
  if (count === 0) {
    test.skip();
    return;
  }
  await sopItems.first().click();

  // Verify the Alert Classifier section appears
  await expect(page.locator("text=Alert Classifier")).toBeVisible({ timeout: 5000 });
  // Verify Dynamic Classifiers sub-section appears
  await expect(page.locator("text=Dynamic Classifiers")).toBeVisible({ timeout: 5000 });
  // Verify the table has header columns
  await expect(page.locator("th:has-text('Field Name')")).toBeVisible();
  await expect(page.locator("th:has-text('Field Value')")).toBeVisible();
});

test("submit feedback on alert detail page", async ({ page }) => {
  const alerts = await getAlertsList(page.request);
  if (alerts.length === 0) {
    test.skip();
    return;
  }
  const alertId = alerts[0]._id;

  await page.goto(`/alerts?id=${alertId}`);
  await expect(page.locator("h2:has-text('Feedback')")).toBeVisible({ timeout: 10000 });

  await page.fill("textarea", "RCA correctly identified the root cause");
  await page.click('button:has-text("Submit Feedback")');

  await expect(page.locator("text=Feedback submitted successfully")).toBeVisible({ timeout: 15000 });
});
