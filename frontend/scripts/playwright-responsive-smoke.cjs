const fs = require('fs');
const path = require('path');

const { chromium, webkit } = require('playwright');
const { PNG } = require('pngjs');

const BASE_URL = 'http://127.0.0.1:4173/';

const TEXT = {
  login: '\u0412\u043e\u0439\u0442\u0438',
  createPass: '\u0421\u043e\u0437\u0434\u0430\u0442\u044c \u043f\u0440\u043e\u043f\u0443\u0441\u043a',
  myPasses: '\u041c\u043e\u0438 \u043f\u0440\u043e\u043f\u0443\u0441\u043a\u0438',
  createPassTitle: '\u0421\u043e\u0437\u0434\u0430\u043d\u0438\u0435 \u043f\u0440\u043e\u043f\u0443\u0441\u043a\u0430',
  subtitle: '\u041a\u043e\u0442\u0442\u0435\u0434\u0436\u043d\u044b\u0439 \u043f\u043e\u0441\u0451\u043b\u043e\u043a',
  pickDate: '\u0412\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u0434\u0430\u0442\u0443',
  done: '\u0413\u043e\u0442\u043e\u0432\u043e',
  cancel: '\u041e\u0442\u043c\u0435\u043d\u0430',
};

const ARTIFACT_PREFIX = path.join(__dirname, '..');

const DEMO_USER = {
  id: 1,
  phone: '+79991234567',
  name: '\u0418\u0432\u0430\u043d\u043e\u0432 \u0418\u0432\u0430\u043d',
  apartment: '25',
  is_admin: false,
};

const pressableByText = (page, text) =>
  page.locator(`xpath=//div[@tabindex="0"][.//*[normalize-space(text())="${text}"]]`).first();

const exactText = (page, text) => page.locator(`xpath=//*[normalize-space(text())="${text}"]`).last();

const exactPressableByText = (page, text) =>
  page.locator(`xpath=//div[@tabindex="0"][.//*[normalize-space(text())="${text}"]]`).first();

const installApiMock = async (page) => {
  await page.route('http://127.0.0.1:8000/**', async (route) => {
    const request = route.request();
    const url = request.url();
    const method = request.method();

    if (url.endsWith('/user/me')) {
      await route.fulfill({
        status: 401,
        contentType: 'application/json; charset=utf-8',
        body: JSON.stringify({ detail: 'Unauthorized' }),
      });
      return;
    }

    if (url.endsWith('/auth/login') && method === 'POST') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json; charset=utf-8',
        body: JSON.stringify({
          access_token: 'playwright-test-token',
          token_type: 'bearer',
          user: DEMO_USER,
        }),
      });
      return;
    }

    if (url.includes('/requests')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json; charset=utf-8',
        body: JSON.stringify([]),
      });
      return;
    }

    if (url.includes('/user/profile')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json; charset=utf-8',
        body: JSON.stringify({
          id: String(DEMO_USER.id),
          login: DEMO_USER.phone,
          fullName: DEMO_USER.name,
          plotNumber: DEMO_USER.apartment,
          phoneNumber: DEMO_USER.phone,
        }),
      });
      return;
    }

    await route.fulfill({
      status: 200,
      contentType: 'application/json; charset=utf-8',
      body: JSON.stringify({}),
    });
  });
};

const sampleScreenshot = (filePath) =>
  new Promise((resolve, reject) => {
    const samples = {};

    fs.createReadStream(filePath)
      .pipe(new PNG())
      .on('parsed', function parsed() {
        const pick = (x, y) => {
          const safeX = Math.max(0, Math.min(this.width - 1, x));
          const safeY = Math.max(0, Math.min(this.height - 1, y));
          const index = (this.width * safeY + safeX) << 2;
          return {
            r: this.data[index],
            g: this.data[index + 1],
            b: this.data[index + 2],
            a: this.data[index + 3],
          };
        };

        samples.bottomCenter = pick(Math.floor(this.width / 2), this.height - 2);
        samples.bottomRight = pick(this.width - 2, this.height - 2);
        samples.midRight = pick(this.width - 2, Math.floor(this.height / 2));
        resolve(samples);
      })
      .on('error', reject);
  });

const isNearWhite = (pixel) => pixel.r >= 245 && pixel.g >= 245 && pixel.b >= 245;

const getWindowMetrics = async (page) =>
  page.evaluate(() => {
    window.scrollTo(0, 10000);
    const root = document.getElementById('root');
    const rootRect = root ? root.getBoundingClientRect() : null;

    return {
      innerWidth: window.innerWidth,
      innerHeight: window.innerHeight,
      scrollX: window.scrollX,
      scrollY: window.scrollY,
      docScrollWidth: document.documentElement.scrollWidth,
      docScrollHeight: document.documentElement.scrollHeight,
      bodyScrollWidth: document.body.scrollWidth,
      rootWidth: rootRect ? rootRect.width : null,
      rootHeight: rootRect ? rootRect.height : null,
    };
  });

const getMonthLabel = async (page) =>
  page.evaluate(() => {
    const values = Array.from(document.querySelectorAll('div'))
      .map((node) => node.textContent?.trim() || '')
      .filter((text) => text.endsWith('\u0433.') && /\d{4}/.test(text) && !/^\d/.test(text));

    return [...new Set(values)][0] || null;
  });

const getGridRect = async (page) =>
  page.evaluate(() => {
    const node = Array.from(document.querySelectorAll('div')).find((item) =>
      /^\d{20,}$/.test((item.textContent || '').trim()),
    );

    if (!node) {
      return null;
    }

    const rect = node.getBoundingClientRect();
    return { x: rect.x, y: rect.y, width: rect.width, height: rect.height };
  });

const getModalRect = async (page) =>
  page.evaluate((texts) => {
    const candidates = Array.from(document.querySelectorAll('div'))
      .map((node) => {
        const text = (node.textContent || '').trim();
        if (!text.includes(texts.pickDate) || !text.includes(texts.cancel) || !text.includes(texts.done)) {
          return null;
        }

        const rect = node.getBoundingClientRect();
        if (rect.width < 200 || rect.height < 200) {
          return null;
        }

        return { x: rect.x, y: rect.y, width: rect.width, height: rect.height, area: rect.width * rect.height };
      })
      .filter(Boolean)
      .sort((left, right) => left.area - right.area);

    if (!candidates.length) {
      return null;
    }

    const { area, ...smallest } = candidates[0];
    return smallest;
  }, TEXT);

const loginToHome = async (page) => {
  await page.goto(BASE_URL, { waitUntil: 'load' });
  await page.locator('input[placeholder="\u041b\u043e\u0433\u0438\u043d"]').waitFor();
  await pressableByText(page, TEXT.login).click();
  await pressableByText(page, TEXT.createPass).waitFor();
};

const openCreatePass = async (page) => {
  await pressableByText(page, TEXT.createPass).click();
  await exactText(page, TEXT.createPassTitle).waitFor();
};

const evaluateHomeViewport = async (browserType, name, viewport, options = {}) => {
  const browser = await browserType.launch({ headless: true });
  const context = await browser.newContext({
    viewport,
    isMobile: Boolean(options.isMobile),
    hasTouch: Boolean(options.hasTouch),
    deviceScaleFactor: 1,
  });
  const page = await context.newPage();

  try {
    await installApiMock(page);

    await page.goto(BASE_URL, { waitUntil: 'load' });
    const authMetrics = await getWindowMetrics(page);

    await pressableByText(page, TEXT.login).click();
    await pressableByText(page, TEXT.createPass).waitFor();

    const homeMetrics = await getWindowMetrics(page);
    const subtitleBox = await exactText(page, TEXT.subtitle).boundingBox();
    const firstButtonBox = await pressableByText(page, TEXT.createPass).boundingBox();
    const lastButtonBox = await pressableByText(page, TEXT.myPasses).boundingBox();
    const screenshotPath = path.join(ARTIFACT_PREFIX, `.tmp-home-${name}.png`);

    await page.screenshot({ path: screenshotPath, fullPage: false });
    const pixelSamples = await sampleScreenshot(screenshotPath);

    return {
      name,
      browser: browserType.name(),
      viewport,
      authNoHorizontalOverflow:
        authMetrics.docScrollWidth <= authMetrics.innerWidth + 1 &&
        authMetrics.bodyScrollWidth <= authMetrics.innerWidth + 1,
      homeNoHorizontalOverflow:
        homeMetrics.docScrollWidth <= homeMetrics.innerWidth + 1 &&
        homeMetrics.bodyScrollWidth <= homeMetrics.innerWidth + 1 &&
        (homeMetrics.rootWidth ?? 0) <= homeMetrics.innerWidth + 1,
      homeWindowLocked: homeMetrics.scrollX === 0 && homeMetrics.scrollY === 0,
      subtitleVisible: Boolean(subtitleBox),
      allHomeButtonsVisible: Boolean(lastButtonBox) && lastButtonBox.y + lastButtonBox.height <= viewport.height,
      logoToButtonGap:
        subtitleBox && firstButtonBox ? Math.round(firstButtonBox.y - (subtitleBox.y + subtitleBox.height)) : null,
      backgroundCovered:
        !isNearWhite(pixelSamples.bottomCenter) &&
        !isNearWhite(pixelSamples.bottomRight) &&
        !isNearWhite(pixelSamples.midRight),
      screenshotPath,
      pixelSamples,
    };
  } finally {
    await context.close();
    await browser.close();
  }
};

const evaluateInputCrosses = async (browserType, name, viewport, options = {}) => {
  const browser = await browserType.launch({ headless: true });
  const context = await browser.newContext({
    viewport,
    isMobile: Boolean(options.isMobile),
    hasTouch: Boolean(options.hasTouch),
    deviceScaleFactor: 1,
  });
  const page = await context.newPage();

  try {
    await installApiMock(page);
    await loginToHome(page);
    await openCreatePass(page);
    await page.locator('input').nth(1).fill('A123AA77');

    const rows = await page.evaluate(() =>
      Array.from(document.querySelectorAll('input'))
        .map((input) => {
          const row = input.parentElement;
          const slot = row && row.lastElementChild !== input ? row.lastElementChild : null;

          if (!row || !slot) {
            return null;
          }

          const rowRect = row.getBoundingClientRect();
          const slotRect = slot.getBoundingClientRect();
          return {
            placeholder: input.getAttribute('placeholder') || '',
            value: input.value,
            rowRightInset: Math.round(rowRect.right - slotRect.right),
            slotWidth: Math.round(slotRect.width),
            slotHeight: Math.round(slotRect.height),
          };
        })
        .filter(Boolean),
    );

    return {
      name,
      browser: browserType.name(),
      viewport,
      rows,
      allRowsInsetCorrect: rows.every((row) => row.rowRightInset >= 8),
    };
  } finally {
    await context.close();
    await browser.close();
  }
};

const evaluateCalendar = async (browserType, name, viewport, options = {}) => {
  const browser = await browserType.launch({ headless: true });
  const context = await browser.newContext({
    viewport,
    isMobile: Boolean(options.isMobile),
    hasTouch: Boolean(options.hasTouch),
    deviceScaleFactor: 1,
  });
  const page = await context.newPage();

  try {
    await installApiMock(page);
    await loginToHome(page);
    await openCreatePass(page);

    const dateButton = page.locator('div[tabindex="0"]').filter({ hasText: /\d{2}\.\d{2}\.\d{4}/ }).last();
    const initialLabel = ((await dateButton.textContent()) || '').replace(/[^\d.]/g, '');

    await dateButton.click();
    await exactText(page, TEXT.pickDate).waitFor();

    const modalRect = await getModalRect(page);
    const monthBeforeSwipe = await getMonthLabel(page);
    const gridRect = await getGridRect(page);
    const modalScreenshot = path.join(ARTIFACT_PREFIX, `.tmp-calendar-open-${name}.png`);

    await page.screenshot({ path: modalScreenshot, fullPage: false });

    if (gridRect) {
      await page.mouse.move(gridRect.x + gridRect.width * 0.8, gridRect.y + gridRect.height * 0.5);
      await page.mouse.down();
      await page.mouse.move(gridRect.x + gridRect.width * 0.2, gridRect.y + gridRect.height * 0.5, { steps: 10 });
      await page.mouse.up();
      await page.waitForTimeout(300);
    }

    const monthAfterSwipe = await getMonthLabel(page);

    await exactPressableByText(page, '15').click();
    await pressableByText(page, TEXT.done).click();
    await page.waitForTimeout(200);

    const savedLabel = ((await dateButton.textContent()) || '').replace(/[^\d.]/g, '');

    return {
      name,
      browser: browserType.name(),
      viewport,
      modalInsideViewport:
        Boolean(modalRect) &&
        modalRect.x >= 0 &&
        modalRect.y >= 0 &&
        modalRect.x + modalRect.width <= viewport.width + 1 &&
        modalRect.y + modalRect.height <= viewport.height + 1,
      swipeChangedMonth:
        Boolean(monthBeforeSwipe) && Boolean(monthAfterSwipe) && monthBeforeSwipe !== monthAfterSwipe,
      initialLabel,
      savedLabel,
      datePersisted: initialLabel !== savedLabel && savedLabel.startsWith('15.'),
      monthBeforeSwipe,
      monthAfterSwipe,
      modalScreenshot,
    };
  } finally {
    await context.close();
    await browser.close();
  }
};

const assertResult = (condition, message) => {
  if (!condition) {
    throw new Error(message);
  }
};

async function main() {
  const responsiveResults = [];

  responsiveResults.push(
    await evaluateHomeViewport(chromium, '375', { width: 375, height: 667 }, { isMobile: true, hasTouch: true }),
  );
  responsiveResults.push(
    await evaluateHomeViewport(chromium, '393', { width: 393, height: 852 }, { isMobile: true, hasTouch: true }),
  );
  responsiveResults.push(
    await evaluateHomeViewport(chromium, '768', { width: 768, height: 1024 }, { isMobile: true, hasTouch: true }),
  );
  responsiveResults.push(
    await evaluateHomeViewport(chromium, '1024', { width: 1024, height: 1366 }, { isMobile: true, hasTouch: true }),
  );
  responsiveResults.push(
    await evaluateHomeViewport(chromium, '1280', { width: 1280, height: 900 }, { isMobile: false, hasTouch: false }),
  );

  for (const result of responsiveResults) {
    assertResult(result.authNoHorizontalOverflow, `${result.name}: auth page still has horizontal overflow`);
    assertResult(result.homeNoHorizontalOverflow, `${result.name}: home page still has horizontal overflow`);
    assertResult(result.homeWindowLocked, `${result.name}: home page still scrolls at window level`);
    assertResult(result.subtitleVisible, `${result.name}: subtitle is missing on home screen`);
    assertResult(result.allHomeButtonsVisible, `${result.name}: home buttons are clipped below the viewport`);
    assertResult(result.backgroundCovered, `${result.name}: screenshot still shows white gaps at the viewport edge`);
    assertResult(
      result.logoToButtonGap !== null && result.logoToButtonGap <= (result.viewport.width <= 480 ? 40 : 72),
      `${result.name}: gap between logo and buttons is too large`,
    );
  }

  const mobileCrosses = await evaluateInputCrosses(
    chromium,
    'crosses-mobile',
    { width: 393, height: 852 },
    { isMobile: true, hasTouch: true },
  );
  const desktopCrosses = await evaluateInputCrosses(
    chromium,
    'crosses-desktop',
    { width: 1280, height: 900 },
    { isMobile: false, hasTouch: false },
  );

  assertResult(mobileCrosses.allRowsInsetCorrect, 'mobile: clear icons are still too close to the right edge');
  assertResult(desktopCrosses.allRowsInsetCorrect, 'desktop: clear icons are still too close to the right edge');

  const chromiumCalendar = await evaluateCalendar(
    chromium,
    '393-chromium',
    { width: 393, height: 852 },
    { isMobile: true, hasTouch: true },
  );
  const webkitCalendar = await evaluateCalendar(
    webkit,
    '393-webkit',
    { width: 393, height: 852 },
    { isMobile: true, hasTouch: true },
  );

  assertResult(chromiumCalendar.modalInsideViewport, 'chromium: calendar modal still exits the viewport');
  assertResult(chromiumCalendar.swipeChangedMonth, 'chromium: calendar swipe did not change month');
  assertResult(chromiumCalendar.datePersisted, 'chromium: selected date was not saved');
  assertResult(webkitCalendar.modalInsideViewport, 'webkit: calendar modal still exits the viewport');
  assertResult(webkitCalendar.datePersisted, 'webkit: selected date was not saved');

  const report = {
    responsive: responsiveResults,
    crosses: {
      mobile: mobileCrosses,
      desktop: desktopCrosses,
    },
    calendar: {
      chromium: chromiumCalendar,
      webkit: webkitCalendar,
    },
  };

  console.log(JSON.stringify(report, null, 2));
}

main().catch((error) => {
  console.error(error.stack || error.message || String(error));
  process.exitCode = 1;
});
