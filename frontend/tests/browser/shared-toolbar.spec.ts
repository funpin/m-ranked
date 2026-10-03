import { expect, test } from "@playwright/test";

test("official rating defaults to first place on every platform and permits manual direction", async ({page}) => {
  for(const platform of ["all","telegram","vk","max","rutube"]) {
    await page.goto(`/review?platform=${platform}`);
    const form=page.getByTestId("filter-toolbar");
    const ascending=form.getByRole("radio",{name:"По возрастанию",exact:true});
    const descending=form.getByRole("radio",{name:"По убыванию",exact:true});
    await form.getByRole("combobox",{name:"Сортировка",exact:true}).selectOption("m_rating");
    await expect(ascending).toBeChecked();
    await form.getByRole("button",{name:"Применить фильтры",exact:true}).click();
    await expect(page).toHaveURL(/sort=m_rating/);
    await expect(page).toHaveURL(/direction=asc/);
    await descending.check();
    await expect(page).toHaveURL(/direction=desc/);
    await page.goto(`/review?platform=${platform}&sort=m_rating`);
    await expect(ascending).toBeChecked();
    await form.getByRole("combobox",{name:"Сортировка",exact:true}).selectOption("anomalies");
    await expect(descending).toBeChecked();
  }
});

test("MAX fits its selection and comparison tabs have a visible selected surface", async ({ page }, info) => {
  test.skip(info.project.name !== "desktop", "The test checks every viewport itself");
  for (const theme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme: theme });
    for (const width of [320, 390, 1280]) {
      await page.setViewportSize({ width, height: 900 });
      for (const path of ["/review?platform=max", "/statistics?platform=max"]) {
        await page.goto(path);
        const max = page.getByTestId("platform-segments").getByRole("radio", { name: "MAX", exact: true });
        await expect(max).toBeChecked();
        const fits = await max.evaluate(input => {
          const label = input.parentElement!, text = label.lastElementChild!;
          const bounds = label.getBoundingClientRect(), textBounds = text.getBoundingClientRect();
          return textBounds.left >= bounds.left && textBounds.right <= bounds.right + 1 && text.scrollWidth <= text.clientWidth;
        });
        expect(fits, `${path} at ${width}px in ${theme}`).toBe(true);
      }
      await page.goto("/compare?platform=max&period=30d");
      const platforms = page.getByTestId("platform-tabs");
      await expect(platforms.getByRole("tab", { name: "MAX", exact: true })).toHaveAttribute("aria-selected", "true");
      const selectedSurface = platforms.locator('[data-slot="motion-highlight"]');
      await expect(selectedSurface).toBeVisible();
      const surface = await selectedSurface.evaluate(el => ({ width: el.getBoundingClientRect().width, height: el.getBoundingClientRect().height, background: getComputedStyle(el).backgroundColor, border: getComputedStyle(el).borderTopStyle }));
      expect(surface.width).toBeGreaterThan(30);
      expect(surface.height).toBeGreaterThan(20);
      expect(surface.background).not.toBe("rgba(0, 0, 0, 0)");
      expect(surface.border).toBe("solid");
      await platforms.getByRole("tab", { name: "TG", exact: true }).click();
      await expect(platforms.getByRole("tab", { name: "TG", exact: true })).toHaveAttribute("aria-selected", "true");
      await expect(page).toHaveURL(/platform=telegram/);
    }
  }
});

test("filter rows fill available space and keep the same geometry on both pages", async ({ page }, info) => {
  test.skip(info.project.name !== "desktop", "The test checks every viewport itself");
  await page.emulateMedia({ colorScheme: "dark" });
  for (const width of [320, 390, 640, 768, 1024, 1280, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    const layouts: unknown[] = [];
    for (const path of ["/review?platform=vk", "/statistics?platform=vk"]) {
      await page.goto(path);
      const toolbar = page.getByTestId("filter-toolbar");
      await expect(toolbar).toBeVisible();
      await expect(toolbar.locator('input[name="period"]')).toHaveCount(4);
      const layout = await toolbar.evaluate(form => {
        const formBox = form.getBoundingClientRect();
        const boxes = [...form.children].filter(e => e.getBoundingClientRect().height > 0)
          .map(e => { const r=e.getBoundingClientRect(); return { x: Math.round(r.x-formBox.x), y: Math.round(r.y-formBox.y), width: Math.round(r.width) }; });
        return { boxes, width: Math.round(formBox.width) };
      });
      for (const y of new Set(layout.boxes.map(box => box.y))) {
        const row = layout.boxes.filter(box => box.y === y);
        expect(Math.max(...row.map(box => box.x+box.width))).toBeGreaterThanOrEqual(layout.width-13);
      }
      if (width >= 1280) expect(new Set(layout.boxes.map(box=>box.y)).size).toBe(1);
      expect(await page.evaluate(()=>document.documentElement.scrollWidth-innerWidth)).toBe(0);
      layouts.push(layout);
      if ([390,768,1440].includes(width)) await toolbar.screenshot({ path: `/tmp/mranked-toolbar-${width}-${path.startsWith("/review") ? "review" : "statistics"}.png` });
    }
    expect(layouts[0]).toEqual(layouts[1]);
  }
});

test("icon-only direction submits and survives browser history", async ({ page }) => {
  await page.goto("/review?platform=vk");
  const toolbar=page.getByTestId("filter-toolbar");
  await toolbar.getByRole("radio", { name: "По возрастанию", exact: true }).check();
  await expect(page).toHaveURL(/direction=asc/);
  await expect(toolbar.getByRole("radio", { name: "По возрастанию", exact: true })).toBeChecked();
  await toolbar.getByRole("radio", { name: "По убыванию", exact: true }).check();
  await expect(page).toHaveURL(/direction=desc/);
  await page.goBack();
  await expect(toolbar.getByRole("radio", { name: "По возрастанию", exact: true })).toBeChecked();
  await page.goto("/statistics?platform=vk");
  await toolbar.getByRole("radio", { name: "По возрастанию", exact: true }).check();
  await expect(page).toHaveURL(/publication_direction=asc/);
});

test("comparison shows sourced student facts and preserves a measured zero", async ({ page }) => {
  await page.goto("/compare?platform=rutube");
  const table=page.getByTestId("compare-table");
  await expect(table.getByRole("columnheader", { name: /Студенты/ })).toBeVisible();
  const row=table.locator("tbody tr").filter({ hasText: "Альфа" });
  await expect(row.locator("td").nth(4)).toHaveText("0");
  const source=row.locator('a[href="https://example.test/students"]');
  await expect(source).toContainText("12 345");
  await expect(source).toHaveAttribute("title", /2026/);
  await table.getByRole("button", { name: /Студенты/ }).click();
  await expect(table.locator("tbody tr").first()).toContainText("Альфа");
  await table.getByRole("button", { name: /Студенты/ }).click();
  await expect(table.locator("tbody tr").first()).toContainText("Альфа");
});

test("contributor image failures leave readable fallbacks", async ({ page }) => {
  await page.route("**/contributors/*.jpg", route => route.abort());
  await page.goto("/review?platform=vk");
  const contributors=page.getByTestId("contributors");
  await expect(contributors.locator("a")).toHaveCount(2);
  await expect(contributors.locator("img")).toHaveCount(0);
  await expect(contributors.locator("a").first()).toContainText(/\w{2}/);
});

test("comparison controls fill their rows and stay inside the toolbar at all widths", async ({ page }, info) => {
  test.skip(info.project.name !== "desktop", "The test checks every viewport itself");
  await page.goto("/compare");
  for (const width of [320,390,640,768,1024,1440]) {
    await page.setViewportSize({ width, height: 900 });
    expect(await page.evaluate(()=>document.documentElement.scrollWidth-innerWidth)).toBe(0);
    const inside=await page.getByTestId("highlight-search").evaluate(input => {
      const search=input.getBoundingClientRect();
      const toolbar=document.querySelector('[data-testid="compare-dashboard"] > div')!.getBoundingClientRect();
      return search.right <= toolbar.right;
    });
    expect(inside, `search outside toolbar at ${width}px`).toBe(true);
    await expect(page.getByRole("tablist", { name: "Период" }).getByRole("tab", { name: "7 д", exact: true })).toBeVisible();
    await expect(page.getByRole("tablist", { name: "Период" }).getByRole("tab", { name: "30 д", exact: true })).toBeVisible();
    const layout = await page.getByTestId("compare-filter-row").evaluate(row => {
      const bounds=row.getBoundingClientRect();
      const boxes=[...row.children].map(el=>{const b=el.getBoundingClientRect();return {y:Math.round(b.top),right:b.right};});
      return {right:bounds.right,boxes};
    });
    for (const y of new Set(layout.boxes.map(box=>box.y))) {
      expect(Math.max(...layout.boxes.filter(box=>box.y===y).map(box=>box.right))).toBeCloseTo(layout.right,0);
    }
    if(width>=768) expect(new Set(layout.boxes.map(box=>box.y)).size).toBe(1);
  }
});
