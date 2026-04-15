const { chromium, webkit } = require('playwright');

const BASE_URL = 'http://127.0.0.1:4173/';

const TEXT = {
  login: 'Войти',
  loginPlaceholder: 'Логин',
  passwordPlaceholder: 'Пароль',
  createPass: 'Создать пропуск',
  createPassTitle: 'Создание пропуска',
  openBarrier: 'Открыть шлагбаум',
  wickets: 'Калитки',
  passes: 'Мои пропуски',
  monitoring: 'Мониторинг',
  exitBarrier: 'Выезд',
  northWicket: 'Калитка Северная (СНТ Пальмира)',
  datePlaceholder: 'ДД.ММ.ГГГГ',
  pickDate: 'Выберите дату',
  done: 'Готово',
  userBarrierMessage: 'Выездной шлагбаум открыт',
  userWicketMessage: 'Северная калитка открыта',
};

const USERS = {
  user: {
    login: 'demo',
    password: 'demo123',
    response: {
      id: '1',
      login: 'demo',
      fullName: 'Иванов Иван',
      plotNumber: '25',
      phoneNumber: '+79991234567',
      isAdmin: false,
    },
  },
  admin: {
    login: 'admin',
    password: 'admin123',
    response: {
      id: '99',
      login: 'admin',
      fullName: 'Администратор',
      plotNumber: '1',
      phoneNumber: '+79990000000',
      isAdmin: true,
    },
  },
};

const DEBUG_MESSAGES = {
  entry: 'DEBUG: entry relay pulse queued',
  exit: 'DEBUG: exit relay pulse queued',
  wicket_north: 'DEBUG: wicket_north relay pulse queued',
  wicket_lake: 'DEBUG: wicket_lake relay pulse queued',
  wicket_admin: 'DEBUG: wicket_admin relay pulse queued',
  wicket_forest: 'DEBUG: wicket_forest relay pulse queued',
};

const pressableByText = (page, text) =>
  page.locator(`xpath=//div[@tabindex="0"][.//*[normalize-space(text())="${text}"]]`).first();

const exactText = (page, text) => page.locator(`xpath=//*[normalize-space(text())="${text}"]`).last();

const inputByPlaceholder = (page, placeholder) => page.locator(`input[placeholder="${placeholder}"]`);

const assertResult = (condition, message) => {
  if (!condition) {
    throw new Error(message);
  }
};

const getWindowMetrics = async (page) =>
  page.evaluate(() => ({
    innerWidth: window.innerWidth,
    innerHeight: window.innerHeight,
    docScrollWidth: document.documentElement.scrollWidth,
    bodyScrollWidth: document.body.scrollWidth,
    scrollX: window.scrollX,
    scrollY: window.scrollY,
  }));

const installApiMock = async (page) => {
  const state = {
    currentUser: null,
  };

  await page.route('**/*', async (route) => {
    const request = route.request();
    const url = request.url();

    if (!url.includes('/auth/') && !url.includes('/user/') && !url.includes('/passes') && !url.includes('/gates/')) {
      await route.continue();
      return;
    }

    if (url.endsWith('/user/me')) {
      if (!state.currentUser) {
        await route.fulfill({
          status: 401,
          contentType: 'application/json; charset=utf-8',
          body: JSON.stringify({ detail: 'Unauthorized' }),
        });
        return;
      }

      await route.fulfill({
        status: 200,
        contentType: 'application/json; charset=utf-8',
        body: JSON.stringify(state.currentUser),
      });
      return;
    }

    if (url.endsWith('/auth/login') && request.method() === 'POST') {
      const payload = request.postDataJSON ? request.postDataJSON() : JSON.parse(request.postData() || '{}');
      const account = Object.values(USERS).find(
        (item) => item.login === payload.login && item.password === payload.password,
      );

      if (!account) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json; charset=utf-8',
          body: JSON.stringify({
            success: false,
            error: 'Неверный логин или пароль',
          }),
        });
        return;
      }

      state.currentUser = account.response;
      await route.fulfill({
        status: 200,
        contentType: 'application/json; charset=utf-8',
        body: JSON.stringify({
          success: true,
          access_token: `${account.login}-token`,
          user: account.response,
          requiresProfileCompletion: false,
        }),
      });
      return;
    }

    if (url.endsWith('/user/profile')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json; charset=utf-8',
        body: JSON.stringify(state.currentUser ?? USERS.user.response),
      });
      return;
    }

    if (url.includes('/passes/my')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json; charset=utf-8',
        body: JSON.stringify([]),
      });
      return;
    }

    if (url.endsWith('/passes') && request.method() === 'POST') {
      const payload = request.postDataJSON ? request.postDataJSON() : JSON.parse(request.postData() || '{}');
      await route.fulfill({
        status: 200,
        contentType: 'application/json; charset=utf-8',
        body: JSON.stringify({
          id: 'pass-1',
          keyType: payload.carNumber ? 'VehicleNumber' : 'Phone',
          keyValue: payload.carNumber ?? payload.phoneNumber ?? '',
          carNumber: payload.carNumber ?? null,
          plotNumber: payload.plotNumber,
          phoneNumber: payload.phoneNumber ?? null,
          expiresAt: payload.expiresAt ?? null,
          isPermanent: Boolean(payload.isPermanent),
          isCourier: Boolean(payload.isCourier),
          status: payload.isPermanent ? 'permanent' : 'active',
          createdAt: new Date().toISOString(),
        }),
      });
      return;
    }

    if (url.endsWith('/gates/open-action') && request.method() === 'POST') {
      const payload = request.postDataJSON ? request.postDataJSON() : JSON.parse(request.postData() || '{}');
      await route.fulfill({
        status: 200,
        contentType: 'application/json; charset=utf-8',
        body: JSON.stringify({
          success: true,
          action: payload.action,
          message: DEBUG_MESSAGES[payload.action],
          timestamp: Date.now(),
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

  return state;
};

const login = async (page, role) => {
  const account = USERS[role];

  await page.goto(BASE_URL, { waitUntil: 'load' });
  await inputByPlaceholder(page, TEXT.loginPlaceholder).waitFor();
  await inputByPlaceholder(page, TEXT.loginPlaceholder).fill(account.login);
  await inputByPlaceholder(page, TEXT.passwordPlaceholder).fill(account.password);
  await pressableByText(page, TEXT.login).click();

  if (role === 'admin') {
    await pressableByText(page, TEXT.monitoring).waitFor();
  } else {
    await pressableByText(page, TEXT.createPass).waitFor();
  }
};

const openCreatePass = async (page) => {
  await pressableByText(page, TEXT.createPass).click();
  await exactText(page, TEXT.createPassTitle).waitFor();
};

const evaluateLayout = async (browserType, name, viewport, options = {}) => {
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
    await login(page, 'user');

    const homeMetrics = await getWindowMetrics(page);
    const createPassButtonBox = await pressableByText(page, TEXT.createPass).boundingBox();
    const passesButtonBox = await pressableByText(page, TEXT.passes).boundingBox();

    await openCreatePass(page);
    const createPassMetrics = await getWindowMetrics(page);

    return {
      name,
      browser: browserType.name(),
      viewport,
      homeNoHorizontalOverflow:
        homeMetrics.docScrollWidth <= homeMetrics.innerWidth + 1 &&
        homeMetrics.bodyScrollWidth <= homeMetrics.innerWidth + 1,
      createPassNoHorizontalOverflow:
        createPassMetrics.docScrollWidth <= createPassMetrics.innerWidth + 1 &&
        createPassMetrics.bodyScrollWidth <= createPassMetrics.innerWidth + 1,
      homeButtonsVisible:
        Boolean(createPassButtonBox) &&
        Boolean(passesButtonBox) &&
        passesButtonBox.y + passesButtonBox.height <= viewport.height + 1,
    };
  } finally {
    await context.close();
    await browser.close();
  }
};

const evaluateInputAffordances = async (browserType, name, viewport, options = {}) => {
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
    await inputByPlaceholder(page, TEXT.loginPlaceholder).waitFor();

    const loginValue = await inputByPlaceholder(page, TEXT.loginPlaceholder).inputValue();
    const passwordValue = await inputByPlaceholder(page, TEXT.passwordPlaceholder).inputValue();

    const authSlot = await page.evaluate((passwordPlaceholder) => {
      const input = document.querySelector(`input[placeholder="${passwordPlaceholder}"]`);
      const row = input?.parentElement;
      const slot = row?.lastElementChild;

      if (!input || !row || !slot || slot === input) {
        return null;
      }

      const rowRect = row.getBoundingClientRect();
      const slotRect = slot.getBoundingClientRect();

      return {
        rowRightInset: Math.round(rowRect.right - slotRect.right),
        slotWithinBounds: slotRect.left >= rowRect.left && slotRect.right <= rowRect.right,
      };
    }, TEXT.passwordPlaceholder);

    await login(page, 'user');
    await openCreatePass(page);

    await inputByPlaceholder(page, TEXT.datePlaceholder).waitFor();
    await page.locator('input').nth(1).fill('A123AA77');

    const createPassSlots = await page.evaluate(() =>
      Array.from(document.querySelectorAll('input'))
        .map((input) => {
          const row = input.parentElement;
          const slot = row?.lastElementChild;

          if (!row || !slot || slot === input) {
            return null;
          }

          const rowRect = row.getBoundingClientRect();
          const slotRect = slot.getBoundingClientRect();

          return {
            placeholder: input.getAttribute('placeholder') || '',
            value: input.value,
            rowRightInset: Math.round(rowRect.right - slotRect.right),
            slotWithinBounds: slotRect.left >= rowRect.left && slotRect.right <= rowRect.right,
          };
        })
        .filter(Boolean),
    );

    return {
      name,
      browser: browserType.name(),
      viewport,
      loginValue,
      passwordValue,
      authSlot,
      createPassSlots,
      dateFieldInitiallyEmpty: (await inputByPlaceholder(page, TEXT.datePlaceholder).inputValue()) === '',
    };
  } finally {
    await context.close();
    await browser.close();
  }
};

const evaluateDateInput = async (browserType, name, viewport, options = {}) => {
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
    await login(page, 'user');
    await openCreatePass(page);

    const dateInput = inputByPlaceholder(page, TEXT.datePlaceholder);
    await dateInput.waitFor();
    await dateInput.fill('15042026');
    const typedValue = await dateInput.inputValue();

    await page.getByLabel('Открыть календарь').click();
    await exactText(page, TEXT.pickDate).waitFor();
    await pressableByText(page, '16').click();
    await pressableByText(page, TEXT.done).click();
    await page.waitForTimeout(200);

    const calendarValue = await dateInput.inputValue();

    return {
      name,
      browser: browserType.name(),
      viewport,
      typedValue,
      calendarValue,
    };
  } finally {
    await context.close();
    await browser.close();
  }
};

const evaluateGateFeedback = async (browserType, name, viewport, role, options = {}) => {
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
    await login(page, role);

    await pressableByText(page, TEXT.openBarrier).click();
    await pressableByText(page, TEXT.exitBarrier).click();

    const barrierText = role === 'admin' ? DEBUG_MESSAGES.exit : TEXT.userBarrierMessage;
    await exactText(page, barrierText).waitFor();
    const wrongBarrierText = role === 'admin' ? TEXT.userBarrierMessage : DEBUG_MESSAGES.exit;

    const barrierWrongVisible = await exactText(page, wrongBarrierText).isVisible().catch(() => false);

    await page.goBack({ waitUntil: 'load' }).catch(() => null);
    await pressableByText(page, TEXT.wickets).waitFor();
    await pressableByText(page, TEXT.wickets).click();
    await pressableByText(page, TEXT.northWicket).click();

    const wicketText = role === 'admin' ? DEBUG_MESSAGES.wicket_north : TEXT.userWicketMessage;
    await exactText(page, wicketText).waitFor();
    const wrongWicketText = role === 'admin' ? TEXT.userWicketMessage : DEBUG_MESSAGES.wicket_north;
    const wicketWrongVisible = await exactText(page, wrongWicketText).isVisible().catch(() => false);

    return {
      name,
      browser: browserType.name(),
      viewport,
      role,
      barrierText,
      wicketText,
      barrierWrongVisible,
      wicketWrongVisible,
    };
  } finally {
    await context.close();
    await browser.close();
  }
};

async function main() {
  const responsive = [
    await evaluateLayout(chromium, 'mobile-chromium', { width: 393, height: 852 }, { isMobile: true, hasTouch: true }),
    await evaluateLayout(chromium, 'desktop-chromium', { width: 1280, height: 900 }, { isMobile: false, hasTouch: false }),
  ];

  for (const result of responsive) {
    assertResult(result.homeNoHorizontalOverflow, `${result.name}: home page still has horizontal overflow`);
    assertResult(result.createPassNoHorizontalOverflow, `${result.name}: create pass page still has horizontal overflow`);
    assertResult(result.homeButtonsVisible, `${result.name}: home buttons are clipped below the viewport`);
  }

  const affordances = [
    await evaluateInputAffordances(
      chromium,
      'mobile-chromium',
      { width: 393, height: 852 },
      { isMobile: true, hasTouch: true },
    ),
    await evaluateInputAffordances(
      chromium,
      'desktop-chromium',
      { width: 1280, height: 900 },
      { isMobile: false, hasTouch: false },
    ),
  ];

  for (const result of affordances) {
    assertResult(result.loginValue === '', `${result.name}: login field is still prefilled`);
    assertResult(result.passwordValue === '', `${result.name}: password field is still prefilled`);
    assertResult(Boolean(result.authSlot?.slotWithinBounds), `${result.name}: password eye is clipped`);
    assertResult((result.authSlot?.rowRightInset ?? 0) >= 8, `${result.name}: password eye is too close to the edge`);
    assertResult(result.dateFieldInitiallyEmpty, `${result.name}: expiration date is still prefilled`);
    assertResult(
      result.createPassSlots.every((row) => row.slotWithinBounds && row.rowRightInset >= 8),
      `${result.name}: one of the input action icons is clipped`,
    );
  }

  const dates = [
    await evaluateDateInput(chromium, 'mobile-chromium', { width: 393, height: 852 }, { isMobile: true, hasTouch: true }),
    await evaluateDateInput(webkit, 'mobile-webkit', { width: 393, height: 852 }, { isMobile: true, hasTouch: true }),
    await evaluateDateInput(chromium, 'desktop-chromium', { width: 1280, height: 900 }, { isMobile: false, hasTouch: false }),
  ];

  for (const result of dates) {
    assertResult(result.typedValue === '15.04.2026', `${result.name}: manual date input did not format correctly`);
    assertResult(result.calendarValue.startsWith('16.'), `${result.name}: calendar selection did not update the input`);
  }

  const gateFeedback = [
    await evaluateGateFeedback(
      chromium,
      'mobile-user',
      { width: 393, height: 852 },
      'user',
      { isMobile: true, hasTouch: true },
    ),
    await evaluateGateFeedback(
      chromium,
      'desktop-admin',
      { width: 1280, height: 900 },
      'admin',
      { isMobile: false, hasTouch: false },
    ),
  ];

  for (const result of gateFeedback) {
    assertResult(!result.barrierWrongVisible, `${result.name}: wrong barrier feedback text is visible`);
    assertResult(!result.wicketWrongVisible, `${result.name}: wrong wicket feedback text is visible`);
  }

  const report = {
    responsive,
    affordances,
    dates,
    gateFeedback,
  };

  console.log(JSON.stringify(report, null, 2));
}

main().catch((error) => {
  console.error(error.stack || error.message || String(error));
  process.exitCode = 1;
});
