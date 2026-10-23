import { expect, test } from "@playwright/test";
import { resolve } from "node:path";

test("5F2E ETA: configure, pause, resume, export, reset", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "创建仿真场景" }),
  ).toBeVisible();
  await page.getByLabel("楼层数量", { exact: true }).fill("5");
  await page.getByLabel("电梯数量", { exact: true }).fill("2");
  await page.getByLabel("每梯容量（人）", { exact: true }).fill("6");
  await page.getByLabel("到达窗口（秒）", { exact: true }).fill("20");
  await page.getByLabel("到达率（人/分钟）", { exact: true }).fill("20");
  await page.getByLabel("运行速度", { exact: true }).selectOption("1");
  await page.screenshot({
    path: resolve("..", "reports", "browser-config.png"),
    fullPage: true,
  });
  await page.getByRole("button", { name: "启动仿真 →", exact: true }).click();
  await expect(page.getByTestId("run-status")).toHaveText("运行中");
  await expect(
    page.getByRole("img", { name: "5层2部电梯实时井道" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "暂停", exact: true }).click();
  await expect(page.getByTestId("run-status")).toHaveText("已暂停");
  await page.screenshot({
    path: resolve("..", "reports", "browser-5F2E.png"),
    fullPage: true,
  });
  await page.getByRole("button", { name: "继续", exact: true }).click();
  await expect(page.getByTestId("run-status")).toHaveText("运行中");
  await page.getByLabel("运行速度控制").selectOption("0");
  await expect(page.getByTestId("run-status")).toHaveText("已完成");
  await page.getByRole("button", { name: "查看1层乘客" }).click();
  await expect(
    page.getByRole("heading", { name: "1F 乘客 · 每页20人" }),
  ).toBeVisible();
  const download = page.waitForEvent("download");
  await page
    .getByRole("link", { name: "metrics.json ↗", exact: true })
    .click();
  const file = await download;
  await file.saveAs(resolve("..", "reports", "browser-metrics.json"));
  await page.getByRole("button", { name: "重置", exact: true }).click();
  await expect(page.getByTestId("run-status")).toHaveText("待启动");
  await page.getByRole("button", { name: "开始", exact: true }).click();
  await expect(page.getByTestId("run-status")).toHaveText("运行中");
  await page.getByRole("button", { name: "停止", exact: true }).click();
  await expect(page.getByTestId("run-status")).toHaveText("已停止");
  expect(errors).toEqual([]);
});

for (const [floors, elevators, policy] of [
  [12, 4, "round_robin"],
  [30, 8, "ppo"],
] as const) {
  test(`${floors}F${elevators}E ${policy}: actual run and trained model`, async ({
    page,
  }) => {
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await page.goto("/");
    await page.getByLabel("楼层数量", { exact: true }).fill(String(floors));
    await page.getByLabel("电梯数量", { exact: true }).fill(String(elevators));
    await page.getByLabel("到达窗口（秒）", { exact: true }).fill("30");
    await page.getByLabel("到达率（人/分钟）", { exact: true }).fill("20");
    await page.getByLabel("调度算法").selectOption(policy);
    if (policy === "ppo")
      await page.getByLabel("已训练模型").selectOption("ppo-curriculum");
    await page.getByLabel("运行速度", { exact: true }).selectOption("0");
    await page.getByRole("button", { name: "启动仿真 →", exact: true }).click();
    await expect(page.getByTestId("run-status")).toHaveText("已完成");
    await expect(page.getByTestId("trend-samples")).toContainText("归档快照");
    const points = await page.getByTestId("trend-samples").textContent();
    expect(Number(points?.match(/·\s*(\d+)点/)?.[1])).toBeGreaterThan(1);
    await expect(
      page.getByRole("img", { name: `${floors}层${elevators}部电梯实时井道` }),
    ).toBeVisible();
    await page.screenshot({
      path: resolve("..", "reports", `browser-${floors}F${elevators}E.png`),
      fullPage: true,
    });
    await expect(
      page.getByRole("link", { name: "passengers.csv ↗", exact: true }),
    ).toBeVisible();
    expect(errors).toEqual([]);
  });
}

test("same-trace experiment, confidence intervals, real training curves", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  await page.getByLabel("楼层数量", { exact: true }).fill("5");
  await page.getByLabel("电梯数量", { exact: true }).fill("2");
  await page.getByLabel("到达窗口（秒）", { exact: true }).fill("30");
  await page.getByRole("button", { name: "03 实验评价" }).click();
  await page.getByLabel("实验模型").selectOption("ppo-curriculum");
  await page.getByRole("button", { name: "运行同流对比", exact: true }).click();
  await expect(page.getByTestId("experiment-status")).toContainText(
    "COMPLETED",
  );
  await expect(
    page.getByRole("cell", { name: "ppo:ppo-curriculum", exact: true }).first(),
  ).toBeVisible();
  await expect(
    page.getByRole("link", {
      name: "confidence_intervals.csv ↗",
      exact: true,
    }),
  ).toBeVisible();
  await expect(
    page.getByRole("img", { name: "真实乘客等待时间箱线分布" }),
  ).toBeVisible();
  const detailButtons = page.getByRole("button", { name: /^查看 [a-f0-9]+$/ });
  await expect(detailButtons).toHaveCount(8);
  await detailButtons.first().click();
  await expect(page.getByRole("heading", { name: /运行详情/ })).toBeVisible();
  const figure = page.waitForEvent("download");
  await page
    .getByRole("link", { name: "figure~wait_distance.svg ↗", exact: true })
    .click();
  await (await figure).saveAs(resolve("..", "reports", "browser-export.svg"));
  await page.screenshot({
    path: resolve("..", "reports", "browser-evaluation.png"),
    fullPage: true,
  });
  await page.getByRole("button", { name: "04 训练与模型" }).click();
  await page.getByLabel("训练记录").selectOption("t3");
  await expect(
    page.getByRole("img", { name: "真实训练Reward和固定验证成本曲线" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "ppo-curriculum", exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: resolve("..", "reports", "browser-training.png"),
    fullPage: true,
  });
  expect(errors).toEqual([]);
});

test("narrow viewport preserves configuration and simulation controls", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await page.getByLabel("楼层数量", { exact: true }).fill("5");
  await page.getByLabel("电梯数量", { exact: true }).fill("2");
  await page.getByLabel("到达窗口（秒）", { exact: true }).fill("10");
  await page.getByLabel("到达率（人/分钟）", { exact: true }).fill("0");
  await page.getByLabel("运行速度", { exact: true }).selectOption("0");
  await page.getByRole("button", { name: "启动仿真 →", exact: true }).click();
  await expect(page.getByTestId("run-status")).toHaveText("已完成");
  await expect(
    page.getByRole("button", { name: "重置", exact: true }),
  ).toBeEnabled();
  await page.screenshot({
    path: resolve("..", "reports", "browser-narrow.png"),
    fullPage: true,
  });
  await page.getByRole("button", { name: "重置", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "开始", exact: true }),
  ).toBeVisible();
});
