const { chromium, webkit } = require('playwright');

const BASE_URL = process.env.PLAYWRIGHT_BASE_URL?.trim() || 'http://127.0.0.1:4173/';
const AUTH_ENTRY_KEY = 'savoya:auth-entry-seen:v1';

const TEXT = {
  authTitle: 'Вход',
  registerTitle: 'Создать аккаунт',
  registerSuccessTitle: 'Аккаунт создан',
  loginPlaceholder: 'Логин',
  passwordPlaceholder: 'Пароль',
  registerNamePlaceholder: 'Иванов Иван',
  registerPhonePlaceholder: '+79991234567',
  registerPlotPlaceholder: '25',
  registerExistingButton: 'У меня уже есть логин и пароль',
  goToAccount: 'Войти в учётную запись',
  createAccount: 'Создать аккаунт',
  createPass: 'Создать пропуск',
  createPassTitle: 'Создание пропуска',
  openBarrier: 'Открыть шлагбаум',
  wickets: 'Калитки',
  passes: 'Мои пропуски',
  users: 'Пользователи',
  usersDbTitle: 'Пользователи в локальной БД',
  datePlaceholder: 'ДД.ММ.ГГГГ',
  pickDate: 'Выберите дату',
  done: 'Готово',
  changePasswordTitle: 'Вы можете сменить пароль',
  newPasswordPlaceholder: 'Введите новый пароль',
  repeatPasswordPlaceholder: 'Повторите новый пароль',
  changePassword: 'Поменять пароль',
  logout: 'Выход',
  searchUsersPlaceholder: 'Логин, ФИО, телефон или участок',
  deleteUser: 'Удалить',
  blockUser: 'Заблокировать',
  unblockUser: 'Разблокировать',
  exitBarrier: 'Выезд',
  northWicket: 'Калитка Северная (СНТ Пальмира)',
  userBarrierMessage: 'Выездной шлагбаум открыт',
  userWicketMessage: 'Северная калитка открыта',
};

const DEBUG_MESSAGES = {
  entry: 'DEBUG: entry relay pulse queued',
  exit: 'DEBUG: exit relay pulse queued',
  wicket_north: 'DEBUG: wicket_north relay pulse queued',
  wicket_lake: 'DEBUG: wicket_lake relay pulse queued',
  wicket_admin: 'DEBUG: wicket_admin relay pulse queued',
  wicket_forest: 'DEBUG: wicket_forest relay pulse queued',
};

const assertResult = (condition, message) => {
  if (!condition) {
    throw new Error(message);
  }
};

const pressableByText = (page, text) =>
  page.locator(`xpath=//div[@tabindex="0"][.//*[normalize-space(text())="${text}"]]`).first();

const exactText = (page, text) => page.locator(`xpath=//*[normalize-space(text())="${text}"]`).first();

const inputByPlaceholder = (page, placeholder) => page.locator(`input[placeholder="${placeholder}"]`);

const getWindowMetrics = async (page) =>
  page.evaluate(() => ({
    innerWidth: window.innerWidth,
    innerHeight: window.innerHeight,
    docScrollWidth: document.documentElement.scrollWidth,
    bodyScrollWidth: document.body.scrollWidth,
  }));

const getInputSlotMetrics = async (page, placeholder) =>
  page.evaluate((currentPlaceholder) => {
    const input = document.querySelector(`input[placeholder="${currentPlaceholder}"]`);
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
  }, placeholder);

const getCreatePassSlotMetrics = async (page) =>
  page.evaluate(() =>
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

const createPassword = () => `Mock!${Math.random().toString(36).slice(2, 9)}9A`;

const buildResident = ({ id, login, fullName, plotNumber, phoneNumber, passwordChangeRequired, ownerIndex }) => ({
  id: String(id),
  login,
  fullName,
  plotNumber,
  phoneNumber,
  isAdmin: false,
  passwordChangeRequired,
  ownerIndex,
  createdAt: new Date().toISOString(),
});

const installApiMock = async (page) => {
  const records = [
    {
      user: buildResident({
        id: 1,
        login: 'demo',
        fullName: 'Иванов Иван',
        plotNumber: '25',
        phoneNumber: '+79991234567',
        passwordChangeRequired: false,
        ownerIndex: 1,
      }),
      password: 'demo123',
      isActive: true,
    },
    {
      user: {
        id: '99',
        login: 'admin',
        fullName: 'Администратор',
        plotNumber: '1',
        phoneNumber: '+79990000000',
        isAdmin: true,
        passwordChangeRequired: false,
      },
      password: 'admin123',
      isActive: true,
    },
  ];

  const state = {
    currentUser: null,
    nextUserId: 200,
    lastRegistered: null,
    lastAdminCreated: null,
  };

  const findRecord = (login) => records.find((item) => item.user.login === login);

  const getResidentRecordsByPlot = (plotNumber) =>
    records.filter((item) => !item.user.isAdmin && item.user.plotNumber === plotNumber);

  const createResidentRecord = ({ fullName, phoneNumber, plotNumber }) => {
    const surname = (fullName.trim().split(/\s+/)[0] || 'user').toLowerCase().replace(/[^a-z0-9]/g, '') || 'user';
    const ownerIndex = getResidentRecordsByPlot(plotNumber).length + 1;
    const baseLogin = `c${ownerIndex}${surname}${plotNumber}`;
    let login = baseLogin;
    let suffix = 2;

    while (findRecord(login)) {
      login = `${baseLogin}${suffix}`;
      suffix += 1;
    }

    const password = createPassword();
    const user = buildResident({
      id: state.nextUserId++,
      login,
      fullName,
      plotNumber,
      phoneNumber,
      passwordChangeRequired: true,
      ownerIndex,
    });
    const record = {
      user,
      password,
      isActive: true,
    };

    records.push(record);
    return record;
  };

  const adminUsersPayload = (search) => {
    const needle = (search || '').trim().toLowerCase();
    const items = records
      .filter((item) => !item.user.isAdmin)
      .filter((item) => {
        if (!needle) {
          return true;
        }
        return [
          item.user.login,
          item.user.fullName,
          item.user.phoneNumber,
          item.user.plotNumber,
        ]
          .join(' ')
          .toLowerCase()
          .includes(needle);
      })
      .slice()
      .reverse()
      .map((item) => ({
        id: Number(item.user.id),
        login: item.user.login,
        password: item.password,
        full_name: item.user.fullName,
        phone: item.user.phoneNumber,
        plot_number: item.user.plotNumber,
        owner_index: item.user.ownerIndex ?? null,
        is_active: item.isActive,
        password_change_required: Boolean(item.user.passwordChangeRequired),
        created_at: item.user.createdAt,
      }));

    return {
      total: items.length,
      items,
    };
  };

  await page.route('**/*', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const pathname = url.pathname;

    if (
      !pathname.includes('/auth/') &&
      !pathname.includes('/user/') &&
      !pathname.includes('/passes') &&
      !pathname.includes('/gates/') &&
      !pathname.includes('/api/admin/users')
    ) {
      await route.continue();
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

    if (pathname.endsWith('/auth/register') && request.method() === 'POST') {
      const payload = request.postDataJSON ? request.postDataJSON() : JSON.parse(request.postData() || '{}');
      const record = createResidentRecord({
        fullName: payload.fullName.trim(),
        phoneNumber: payload.phoneNumber.trim(),
        plotNumber: payload.plotNumber.trim(),
      });
      state.lastRegistered = record;

      await route.fulfill({
        status: 200,
        contentType: 'application/json; charset=utf-8',
        body: JSON.stringify({
          success: true,
          login: record.user.login,
          password: record.password,
          user: record.user,
        }),
      });
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

      if (!record.isActive) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json; charset=utf-8',
          body: JSON.stringify({
            success: false,
            error: 'User is inactive',
          }),
        });
        return;
      }

      state.currentUser = { ...record.user };
      await route.fulfill({
        status: 200,
        contentType: 'application/json; charset=utf-8',
        body: JSON.stringify({
          success: true,
          access_token: `${record.user.login}-token`,
          user: state.currentUser,
          requiresProfileCompletion: false,
          passwordChangeRequired: Boolean(state.currentUser.passwordChangeRequired),
        }),
      });
      return;
    }

    if (pathname.endsWith('/user/password') && request.method() === 'PUT') {
      const payload = request.postDataJSON ? request.postDataJSON() : JSON.parse(request.postData() || '{}');
      const record = state.currentUser ? findRecord(state.currentUser.login) : null;

      if (!record) {
        await route.fulfill({
          status: 401,
          contentType: 'application/json; charset=utf-8',
          body: JSON.stringify({ detail: 'Unauthorized' }),
        });
        return;
      }

      record.password = payload.newPassword;
      record.user = {
        ...record.user,
        passwordChangeRequired: false,
      };
      state.currentUser = { ...record.user };

      await route.fulfill({
        status: 200,
        contentType: 'application/json; charset=utf-8',
        body: JSON.stringify(state.currentUser),
      });
      return;
    }

    if (pathname.endsWith('/user/profile') && request.method() === 'PUT') {
      const payload = request.postDataJSON ? request.postDataJSON() : JSON.parse(request.postData() || '{}');
      const record = state.currentUser ? findRecord(state.currentUser.login) : null;
      if (!record) {
        await route.fulfill({
          status: 401,
          contentType: 'application/json; charset=utf-8',
          body: JSON.stringify({ detail: 'Unauthorized' }),
        });
        return;
      }

      record.user = {
        ...record.user,
        fullName: payload.fullName,
        plotNumber: payload.plotNumber || record.user.plotNumber,
      };
      state.currentUser = { ...record.user };

      await route.fulfill({
        status: 200,
        contentType: 'application/json; charset=utf-8',
        body: JSON.stringify(state.currentUser),
      });
      return;
    }

    if (pathname.includes('/api/admin/users')) {
      if (pathname.endsWith('/api/admin/users') && request.method() === 'GET') {
        await route.fulfill({
          status: 200,
          contentType: 'application/json; charset=utf-8',
          body: JSON.stringify(adminUsersPayload(url.searchParams.get('search'))),
        });
        return;
      }

      if (pathname.endsWith('/api/admin/users') && request.method() === 'POST') {
        const payload = request.postDataJSON ? request.postDataJSON() : JSON.parse(request.postData() || '{}');
        const record = createResidentRecord({
          fullName: payload.full_name.trim(),
          phoneNumber: payload.phone.trim(),
          plotNumber: payload.plot_number.trim(),
        });
        state.lastAdminCreated = record;

        await route.fulfill({
          status: 200,
          contentType: 'application/json; charset=utf-8',
          body: JSON.stringify({
            id: Number(record.user.id),
            login: record.user.login,
            password: record.password,
            full_name: record.user.fullName,
            phone: record.user.phoneNumber,
            plot_number: record.user.plotNumber,
            owner_index: record.user.ownerIndex ?? null,
            is_active: record.isActive,
            password_change_required: Boolean(record.user.passwordChangeRequired),
            created_at: record.user.createdAt,
          }),
        });
        return;
      }

      const match = pathname.match(/\/api\/admin\/users\/(\d+)(?:\/(block|unblock))?$/);
      if (match) {
        const userId = match[1];
        const action = match[2];
        const record = records.find((item) => item.user.id === String(userId));

        if (!record) {
          await route.fulfill({
            status: 404,
            contentType: 'application/json; charset=utf-8',
            body: JSON.stringify({ detail: 'Not found' }),
          });
          return;
        }

        if (request.method() === 'DELETE') {
          const index = records.findIndex((item) => item.user.id === String(userId));
          records.splice(index, 1);
          if (state.lastAdminCreated?.user.id === String(userId)) {
            state.lastAdminCreated = null;
          }
          await route.fulfill({
            status: 200,
            contentType: 'application/json; charset=utf-8',
            body: JSON.stringify({ message: 'Пользователь удалён' }),
          });
          return;
        }

        if (request.method() === 'POST' && action) {
          record.isActive = action === 'unblock';
          await route.fulfill({
            status: 200,
            contentType: 'application/json; charset=utf-8',
            body: JSON.stringify({
              id: Number(record.user.id),
              login: record.user.login,
              password: record.password,
              full_name: record.user.fullName,
              phone: record.user.phoneNumber,
              plot_number: record.user.plotNumber,
              owner_index: record.user.ownerIndex ?? null,
              is_active: record.isActive,
              password_change_required: Boolean(record.user.passwordChangeRequired),
              created_at: record.user.createdAt,
            }),
          });
          return;
        }
      }
    }

    if (pathname.endsWith('/passes/my')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json; charset=utf-8',
        body: JSON.stringify([]),
      });
      return;
    }

    if (pathname.endsWith('/passes') && request.method() === 'POST') {
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

    if (pathname.endsWith('/gates/open-action') && request.method() === 'POST') {
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

const openCreatePass = async (page) => {
  await pressableByText(page, TEXT.createPass).click();
  await exactText(page, TEXT.createPassTitle).waitFor();
};

const login = async (page, loginValue, password) => {
  await inputByPlaceholder(page, TEXT.loginPlaceholder).fill(loginValue);
  await inputByPlaceholder(page, TEXT.passwordPlaceholder).fill(password);
  await pressableByText(page, 'Войти').click();
};

const setSeenFlag = async (page) => {
  await page.addInitScript((key) => {
    window.localStorage.setItem(key, 'seen');
  }, AUTH_ENTRY_KEY);
};

const ensureAuthScreen = async (page) => {
  if ((await inputByPlaceholder(page, TEXT.registerNamePlaceholder).count()) > 0) {
    await pressableByText(page, TEXT.registerExistingButton).click();
  }
  await inputByPlaceholder(page, TEXT.loginPlaceholder).waitFor();
};

const evaluateMobileResidentScenario = async (browserType, name, viewport, options = {}) => {
  const browser = await browserType.launch({ headless: true });
  const context = await browser.newContext({
    viewport,
    isMobile: Boolean(options.isMobile),
    hasTouch: Boolean(options.hasTouch),
    deviceScaleFactor: 1,
  });
  const page = await context.newPage();

  try {
    const state = await installApiMock(page);

    await page.goto(BASE_URL, { waitUntil: 'load' });
    await inputByPlaceholder(page, TEXT.registerNamePlaceholder).waitFor();

    const firstVisitIsRegister = await inputByPlaceholder(page, TEXT.registerNamePlaceholder).isVisible();
    const loginFieldOnFirstVisit = await inputByPlaceholder(page, TEXT.loginPlaceholder).count();

    await inputByPlaceholder(page, TEXT.registerNamePlaceholder).fill('Ivanov Ivan');
    await inputByPlaceholder(page, TEXT.registerPhonePlaceholder).fill('+79990001234');
    await inputByPlaceholder(page, TEXT.registerPlotPlaceholder).fill('47');
    await pressableByText(page, TEXT.createAccount).click();

    await exactText(page, TEXT.registerSuccessTitle).waitFor();
    const generatedLogin = state.lastRegistered?.user.login;
    const generatedPassword = state.lastRegistered?.password;

    assertResult(Boolean(generatedLogin), `${name}: register flow did not produce a login`);
    assertResult(Boolean(generatedPassword), `${name}: register flow did not produce a password`);

    await exactText(page, generatedLogin).waitFor();
    await exactText(page, generatedPassword).waitFor();
    await pressableByText(page, TEXT.goToAccount).click();

    await inputByPlaceholder(page, TEXT.loginPlaceholder).waitFor();
    const loginValue = await inputByPlaceholder(page, TEXT.loginPlaceholder).inputValue();
    const passwordValue = await inputByPlaceholder(page, TEXT.passwordPlaceholder).inputValue();
    const authSlot = await getInputSlotMetrics(page, TEXT.passwordPlaceholder);

    await login(page, generatedLogin, generatedPassword);
    await pressableByText(page, TEXT.createPass).waitFor();
    await exactText(page, TEXT.changePasswordTitle).waitFor();

    const newPasswordSlot = await getInputSlotMetrics(page, TEXT.newPasswordPlaceholder);
    const repeatPasswordSlot = await getInputSlotMetrics(page, TEXT.repeatPasswordPlaceholder);

    await inputByPlaceholder(page, TEXT.newPasswordPlaceholder).fill('NewStrong!91');
    await inputByPlaceholder(page, TEXT.repeatPasswordPlaceholder).fill('NewStrong!91');
    await pressableByText(page, TEXT.changePassword).click();
    await exactText(page, TEXT.changePasswordTitle).waitFor({ state: 'detached' });

    const homeMetrics = await getWindowMetrics(page);
    await openCreatePass(page);
    const createPassMetrics = await getWindowMetrics(page);
    const createPassSlots = await getCreatePassSlotMetrics(page);

    const dateInput = inputByPlaceholder(page, TEXT.datePlaceholder);
    const dateFieldInitiallyEmpty = (await dateInput.inputValue()) === '';
    await dateInput.fill('15042026');
    const typedDateValue = await dateInput.inputValue();

    await page.getByLabel('Открыть календарь').click();
    await exactText(page, TEXT.pickDate).waitFor();
    await pressableByText(page, '16').click();
    await pressableByText(page, TEXT.done).click();
    await page.waitForTimeout(200);
    const calendarDateValue = await dateInput.inputValue();

    await page.getByLabel('Назад').click();
    await pressableByText(page, TEXT.createPass).waitFor();

    await pressableByText(page, TEXT.openBarrier).click();
    await pressableByText(page, TEXT.exitBarrier).click();
    await exactText(page, TEXT.userBarrierMessage).waitFor();
    const debugBarrierVisible = (await exactText(page, DEBUG_MESSAGES.exit).count()) > 0;

    await page.getByLabel('Назад').click();
    await pressableByText(page, TEXT.wickets).waitFor();
    await pressableByText(page, TEXT.wickets).click();
    await pressableByText(page, TEXT.northWicket).click();
    await exactText(page, TEXT.userWicketMessage).waitFor();
    const debugWicketVisible = (await exactText(page, DEBUG_MESSAGES.wicket_north).count()) > 0;

    await page.getByLabel('Назад').click();
    await pressableByText(page, TEXT.logout).click();
    await inputByPlaceholder(page, TEXT.loginPlaceholder).waitFor();

    await page.goto(BASE_URL, { waitUntil: 'load' });
    await inputByPlaceholder(page, TEXT.loginPlaceholder).waitFor();
    const secondVisitShowsAuth = (await inputByPlaceholder(page, TEXT.loginPlaceholder).count()) === 1;
    const registerVisibleOnSecondVisit = (await inputByPlaceholder(page, TEXT.registerNamePlaceholder).count()) > 0;

    return {
      name,
      browser: browserType.name(),
      viewport,
      firstVisitIsRegister,
      loginFieldOnFirstVisit,
      loginValue,
      passwordValue,
      authSlot,
      newPasswordSlot,
      repeatPasswordSlot,
      homeNoHorizontalOverflow:
        homeMetrics.docScrollWidth <= homeMetrics.innerWidth + 1 &&
        homeMetrics.bodyScrollWidth <= homeMetrics.innerWidth + 1,
      createPassNoHorizontalOverflow:
        createPassMetrics.docScrollWidth <= createPassMetrics.innerWidth + 1 &&
        createPassMetrics.bodyScrollWidth <= createPassMetrics.innerWidth + 1,
      createPassSlots,
      dateFieldInitiallyEmpty,
      typedDateValue,
      calendarDateValue,
      debugBarrierVisible,
      debugWicketVisible,
      secondVisitShowsAuth,
      registerVisibleOnSecondVisit,
    };
  } finally {
    await context.close();
    await browser.close();
  }
};

const evaluateMobileWebkitDateScenario = async (browserType, name, viewport, options = {}) => {
  const browser = await browserType.launch({ headless: true });
  const context = await browser.newContext({
    viewport,
    isMobile: Boolean(options.isMobile),
    hasTouch: Boolean(options.hasTouch),
    deviceScaleFactor: 1,
  });
  const page = await context.newPage();

  try {
    await setSeenFlag(page);
    await installApiMock(page);

    await page.goto(BASE_URL, { waitUntil: 'load' });
    await ensureAuthScreen(page);
    await login(page, 'demo', 'demo123');
    await pressableByText(page, TEXT.createPass).waitFor();
    await openCreatePass(page);

    const dateInput = inputByPlaceholder(page, TEXT.datePlaceholder);
    await dateInput.fill('15042026');
    const typedDateValue = await dateInput.inputValue();

    await page.getByLabel('Открыть календарь').click();
    await exactText(page, TEXT.pickDate).waitFor();
    await pressableByText(page, '16').click();
    await pressableByText(page, TEXT.done).click();
    await page.waitForTimeout(200);

    return {
      name,
      browser: browserType.name(),
      viewport,
      typedDateValue,
      calendarDateValue: await dateInput.inputValue(),
    };
  } finally {
    await context.close();
    await browser.close();
  }
};

const evaluateDesktopAdminScenario = async (browserType, name, viewport, options = {}) => {
  const browser = await browserType.launch({ headless: true });
  const context = await browser.newContext({
    viewport,
    isMobile: Boolean(options.isMobile),
    hasTouch: Boolean(options.hasTouch),
    deviceScaleFactor: 1,
  });
  const page = await context.newPage();

  try {
    await setSeenFlag(page);
    const state = await installApiMock(page);

    await page.goto(BASE_URL, { waitUntil: 'load' });
    await ensureAuthScreen(page);
    await login(page, 'admin', 'admin123');
    await pressableByText(page, TEXT.users).waitFor();
    await pressableByText(page, TEXT.users).click();
    await exactText(page, TEXT.usersDbTitle).waitFor();

    await inputByPlaceholder(page, TEXT.registerNamePlaceholder).fill('Petrov Petr');
    await inputByPlaceholder(page, TEXT.registerPhonePlaceholder).fill('+79995550123');
    await inputByPlaceholder(page, TEXT.registerPlotPlaceholder).fill('88');
    await pressableByText(page, 'Создать пользователя').click();

    const createdLogin = state.lastAdminCreated?.user.login;
    const createdPassword = state.lastAdminCreated?.password;

    assertResult(Boolean(createdLogin), `${name}: admin create user did not return a login`);
    assertResult(Boolean(createdPassword), `${name}: admin create user did not return a password`);

    await exactText(page, createdLogin).waitFor();
    await exactText(page, createdPassword).waitFor();

    await inputByPlaceholder(page, TEXT.searchUsersPlaceholder).fill(createdLogin);
    await exactText(page, createdLogin).waitFor();

    await pressableByText(page, TEXT.blockUser).click();
    await exactText(page, `Пользователь ${createdLogin} заблокирован`).waitFor();

    await pressableByText(page, TEXT.unblockUser).click();
    await exactText(page, `Пользователь ${createdLogin} разблокирован`).waitFor();

    page.once('dialog', (dialog) => dialog.accept());
    await pressableByText(page, TEXT.deleteUser).click();
    await exactText(page, `Пользователь ${createdLogin} удалён`).waitFor();
    await exactText(page, 'Пользователи не найдены').waitFor();

    return {
      name,
      browser: browserType.name(),
      viewport,
      createdLogin,
      createdPassword,
      emptyStateVisible: (await exactText(page, 'Пользователи не найдены').count()) > 0,
    };
  } finally {
    await context.close();
    await browser.close();
  }
};

async function main() {
  const mobileResident = await evaluateMobileResidentScenario(
    chromium,
    'mobile-chromium-resident',
    { width: 393, height: 852 },
    { isMobile: true, hasTouch: true },
  );

  assertResult(mobileResident.firstVisitIsRegister, 'mobile resident: first visit no longer opens account creation');
  assertResult(mobileResident.loginFieldOnFirstVisit === 0, 'mobile resident: login screen opened on first visit');
  assertResult(mobileResident.loginValue === '', 'mobile resident: login field is prefilled');
  assertResult(mobileResident.passwordValue === '', 'mobile resident: password field is prefilled');
  assertResult(Boolean(mobileResident.authSlot?.slotWithinBounds), 'mobile resident: auth eye icon is clipped');
  assertResult((mobileResident.authSlot?.rowRightInset ?? 0) >= 8, 'mobile resident: auth eye icon is too close to edge');
  assertResult(Boolean(mobileResident.newPasswordSlot?.slotWithinBounds), 'mobile resident: new password eye icon is clipped');
  assertResult(Boolean(mobileResident.repeatPasswordSlot?.slotWithinBounds), 'mobile resident: repeat password eye icon is clipped');
  assertResult(mobileResident.homeNoHorizontalOverflow, 'mobile resident: home page still has horizontal overflow');
  assertResult(mobileResident.createPassNoHorizontalOverflow, 'mobile resident: create pass page still has horizontal overflow');
  assertResult(mobileResident.dateFieldInitiallyEmpty, 'mobile resident: expiration date is still prefilled');
  assertResult(mobileResident.typedDateValue === '15.04.2026', 'mobile resident: manual date input did not format correctly');
  assertResult(
    mobileResident.calendarDateValue.startsWith('16.'),
    'mobile resident: calendar selection did not update the date field',
  );
  assertResult(
    mobileResident.createPassSlots.every((row) => row.slotWithinBounds && row.rowRightInset >= 8),
    'mobile resident: one of the create-pass icons is clipped',
  );
  assertResult(!mobileResident.debugBarrierVisible, 'mobile resident: debug barrier text is visible for regular user');
  assertResult(!mobileResident.debugWicketVisible, 'mobile resident: debug wicket text is visible for regular user');
  assertResult(mobileResident.secondVisitShowsAuth, 'mobile resident: second visit does not open the auth screen');
  assertResult(!mobileResident.registerVisibleOnSecondVisit, 'mobile resident: register screen still appears on second visit');

  const mobileWebkitDate = await evaluateMobileWebkitDateScenario(
    webkit,
    'mobile-webkit-date',
    { width: 393, height: 852 },
    { isMobile: true, hasTouch: true },
  );

  assertResult(
    mobileWebkitDate.typedDateValue === '15.04.2026',
    'mobile webkit: manual date input did not format correctly',
  );
  assertResult(
    mobileWebkitDate.calendarDateValue.startsWith('16.'),
    'mobile webkit: calendar selection did not update the date field',
  );

  const desktopAdmin = await evaluateDesktopAdminScenario(
    chromium,
    'desktop-chromium-admin',
    { width: 1440, height: 960 },
    { isMobile: false, hasTouch: false },
  );

  assertResult(desktopAdmin.emptyStateVisible, 'desktop admin: deleted user is still visible in the filtered table');

  console.log(
    JSON.stringify(
      {
        mobileResident,
        mobileWebkitDate,
        desktopAdmin,
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
