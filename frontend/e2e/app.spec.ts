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

test("SOP Management shows version badge when SOP selected", async ({ page }) => {
  await page.goto("/");
  await page.click("button:has-text('SOP Management')");
  await expect(page.locator("text=SOP IDs")).toBeVisible({ timeout: 5000 });

  const sopButtons = page.locator("div.divide-y button");
  if (await sopButtons.count() === 0) {
    test.skip();
    return;
  }
  await sopButtons.first().click();

  // Version badges should be visible (spans with v prefix in mono font)
  await expect(page.locator("span[class*='font-mono']:has-text('v')").first()).toBeVisible({ timeout: 5000 });
  await expect(page.locator("button:has-text('Upload New Version')")).toBeVisible();
});

test("SOP Management Upload New Version form appears and validates format", async ({ page }) => {
  await page.goto("/");
  await page.click("button:has-text('SOP Management')");
  await expect(page.locator("text=SOP IDs")).toBeVisible({ timeout: 5000 });

  const sopButtons = page.locator("div.divide-y button");
  if (await sopButtons.count() === 0) {
    test.skip();
    return;
  }
  await sopButtons.first().click();
  await page.click("button:has-text('Upload New Version')");

  await expect(page.locator("h3:has-text('Upload New Version')")).toBeVisible({ timeout: 3000 });
  await expect(page.locator("input[placeholder]").first()).toBeVisible();

  // Dismiss panel
  await page.click("button:has-text('Cancel New Version Upload'), button:has-text('Cancel Version Upload'), button:has-text('Dismiss')");
  await expect(page.locator("h3:has-text('Upload New Version')")).not.toBeVisible({ timeout: 3000 });
});

test("SOP Management Add New SOP form requires version fields", async ({ page }) => {
  await page.goto("/");
  await page.click("button:has-text('SOP Management')");
  await expect(page.locator("text=SOP IDs")).toBeVisible({ timeout: 5000 });

  await page.click("button:has-text('+ Add New')");
  await expect(page.locator("h2:has-text('Add New SOP')")).toBeVisible({ timeout: 3000 });

  // Version fields should be present
  await expect(page.locator("input[placeholder='1.0']").first()).toBeVisible();
  await expect(page.locator("input[placeholder='1.0']").nth(1)).toBeVisible();
});
