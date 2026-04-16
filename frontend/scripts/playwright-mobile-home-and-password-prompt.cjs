const { chromium, webkit, devices } = require('playwright');

const BASE_URL = process.env.PLAYWRIGHT_BASE_URL?.trim() || 'http://127.0.0.1:4173/';
const AUTH_ENTRY_KEY = 'savoya:auth-entry-seen:v1';

const TEXT = {
  loginPlaceholder: 'Логин',
  passwordPlaceholder: 'Пароль',
  signIn: 'Войти',
  createPass: 'Создать пропуск',
  openBarrier: 'Открыть шлагбаум',
  wickets: 'Калитки',
  myPasses: 'Мои пропуски',
  logout: 'Выход',
  changePasswordTitle: 'Вы можете сменить пароль',
  dismissPasswordChange: 'Оставить',
};

const assertResult = (condition, message) => {
  if (!condition) {
    throw new Error(message);
  }
};

const pressableByText = (page, text) =>
  page.locator(`xpath=//div[@tabindex="0"][.//*[normalize-space(text())="${text}"]]`).first();

const inputByPlaceholder = (page, placeholder) => page.locator(`input[placeholder="${placeholder}"]`);

const setSeenFlag = async (page) => {
  await page.addInitScript((key) => {
    window.localStorage.setItem(key, 'seen');
  }, AUTH_ENTRY_KEY);
};

const buildResident = ({ id, login, fullName, plotNumber, phoneNumber, password, passwordChangeRequired }) => ({
  user: {
    id: String(id),
    login,
    fullName,
    plotNumber,
    phoneNumber,
    isAdmin: false,
    passwordChangeRequired,
    passwordChangePromptRequired: false,
  },
  password,
  passwordChangePromptShown: false,
});

const installApiMock = async (page) => {
  const records = [
    buildResident({
      id: 1,
      login: 'resident',
      fullName: 'Иванов Иван',
      plotNumber: '25',
      phoneNumber: '+79991234567',
      password: 'Temp!Pass91',
      passwordChangeRequired: true,
    }),
  ];

  const state = {
    currentUser: null,
  };

  const findRecord = (login) => records.find((item) => item.user.login === login);

  await page.route('**/*', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const pathname = url.pathname;

    if (!pathname.includes('/auth/') && !pathname.includes('/user/')) {
      await route.continue();
      return;
    }

    if (pathname.endsWith('/auth/login') && request.method() === 'POST') {
      const payload = request.postDataJSON ? request.postDataJSON() : JSON.parse(request.postData() || '{}');
      const record = findRecord(payload.login);

      if (!record || record.password !== payload.password) {
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

      const shouldPrompt = Boolean(record.user.passwordChangeRequired && !record.passwordChangePromptShown);
      record.passwordChangePromptShown = true;
      state.currentUser = {
        ...record.user,
        passwordChangePromptRequired: false,
      };

      await route.fulfill({
        status: 200,
        contentType: 'application/json; charset=utf-8',
        body: JSON.stringify({
          success: true,
          access_token: `mock-token-${record.user.id}`,
          user: {
            ...state.currentUser,
            passwordChangePromptRequired: shouldPrompt,
          },
          requiresProfileCompletion: false,
          passwordChangeRequired: Boolean(record.user.passwordChangeRequired),
        }),
      });
      return;
    }

    if (pathname.endsWith('/user/me')) {
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

    if (pathname.endsWith('/auth/logout')) {
      state.currentUser = null;
      await route.fulfill({
        status: 200,
        contentType: 'application/json; charset=utf-8',
        body: JSON.stringify({ message: 'ok' }),
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

const login = async (page, loginValue, password) => {
  await inputByPlaceholder(page, TEXT.loginPlaceholder).fill(loginValue);
  await inputByPlaceholder(page, TEXT.passwordPlaceholder).fill(password);
  await pressableByText(page, TEXT.signIn).click();
};

const collectHomeLayout = async (page) =>
  page.evaluate((labels) => {
    const buttons = labels
      .map((label) => {
        const node = Array.from(document.querySelectorAll('div[tabindex="0"]')).find((candidate) => {
          const text = candidate.textContent?.replace(/\s+/g, ' ').trim();
          return text === label;
        });

        if (!node) {
          return null;
        }

        const rect = node.getBoundingClientRect();
        return {
          label,
          top: Math.round(rect.top),
          bottom: Math.round(rect.bottom),
          height: Math.round(rect.height),
        };
      })
      .filter(Boolean);

    const logo =
      Array.from(document.querySelectorAll('img')).find((node) =>
        (node.getAttribute('src') || '').includes('home-logo-reference'),
      ) ?? null;
    const logoRect = logo ? logo.getBoundingClientRect() : null;
    const firstButton = buttons[0] ?? null;

    return {
      viewportHeight: window.innerHeight,
      docScrollHeight: document.documentElement.scrollHeight,
      bodyScrollHeight: document.body.scrollHeight,
      buttons,
      logoBottom: logoRect ? Math.round(logoRect.bottom) : null,
      firstButtonTop: firstButton ? firstButton.top : null,
      logoToButtonsGap:
        logoRect && firstButton ? Math.max(0, Math.round(firstButton.top - logoRect.bottom)) : null,
    };
  }, [TEXT.createPass, TEXT.openBarrier, TEXT.wickets, TEXT.myPasses, TEXT.logout]);

const runScenario = async ({ browserType, name, contextOptions, maxGap }) => {
  const browser = await browserType.launch({ headless: true });
  const context = await browser.newContext({
    ...contextOptions,
    ignoreHTTPSErrors: true,
    deviceScaleFactor: contextOptions.deviceScaleFactor ?? 1,
  });
  const page = await context.newPage();

  try {
    await setSeenFlag(page);
    await installApiMock(page);

    await page.goto(BASE_URL, { waitUntil: 'load' });
    await inputByPlaceholder(page, TEXT.loginPlaceholder).waitFor();

    await login(page, 'resident', 'Temp!Pass91');
    await pressableByText(page, TEXT.createPass).waitFor();
    await page.locator(`xpath=//*[normalize-space(text())="${TEXT.changePasswordTitle}"]`).waitFor();

    const promptVisibleFirstLogin = (await page.locator(`xpath=//*[normalize-space(text())="${TEXT.changePasswordTitle}"]`).count()) > 0;
    await pressableByText(page, TEXT.dismissPasswordChange).click();
    await page.locator(`xpath=//*[normalize-space(text())="${TEXT.changePasswordTitle}"]`).waitFor({ state: 'detached' });

    const layout = await collectHomeLayout(page);
    assertResult(layout.buttons.length === 5, `${name}: not all home buttons are rendered`);
    assertResult(
      layout.buttons.every((item) => item.bottom <= layout.viewportHeight - 1),
      `${name}: one of the home buttons is still outside the viewport`,
    );
    assertResult(
      layout.docScrollHeight <= layout.viewportHeight + 1 && layout.bodyScrollHeight <= layout.viewportHeight + 1,
      `${name}: home screen still requires vertical scrolling`,
    );
    assertResult(
      typeof layout.logoToButtonsGap === 'number' && layout.logoToButtonsGap <= maxGap,
      `${name}: logo gap is still too large`,
    );

    await pressableByText(page, TEXT.logout).click();
    await inputByPlaceholder(page, TEXT.loginPlaceholder).waitFor();

    await login(page, 'resident', 'Temp!Pass91');
    await pressableByText(page, TEXT.createPass).waitFor();
    await page.waitForTimeout(250);

    const promptVisibleSecondLogin =
      (await page.locator(`xpath=//*[normalize-space(text())="${TEXT.changePasswordTitle}"]`).count()) > 0;

    return {
      name,
      browser: browserType.name(),
      promptVisibleFirstLogin,
      promptVisibleSecondLogin,
      layout,
    };
  } finally {
    await context.close();
    await browser.close();
  }
};

async function main() {
  const compactAndroid = await runScenario({
    browserType: chromium,
    name: 'compact-android-chromium',
    contextOptions: {
      viewport: { width: 360, height: 640 },
      isMobile: true,
      hasTouch: true,
      userAgent: devices['Pixel 5'].userAgent,
    },
    maxGap: 24,
  });

  assertResult(compactAndroid.promptVisibleFirstLogin, 'compact android: password prompt did not appear on first login');
  assertResult(!compactAndroid.promptVisibleSecondLogin, 'compact android: password prompt appeared again after dismiss');

  const iphoneSe = await runScenario({
    browserType: webkit,
    name: 'iphone-se-webkit',
    contextOptions: {
      ...devices['iPhone SE'],
    },
    maxGap: 28,
  });

  assertResult(iphoneSe.promptVisibleFirstLogin, 'iphone se: password prompt did not appear on first login');
  assertResult(!iphoneSe.promptVisibleSecondLogin, 'iphone se: password prompt appeared again after dismiss');

  console.log(
    JSON.stringify(
      {
        compactAndroid,
        iphoneSe,
      },
      null,
      2,
    ),
  );
}

main().catch((error) => {
  console.error(error.stack || error.message || String(error));
  process.exitCode = 1;
});
