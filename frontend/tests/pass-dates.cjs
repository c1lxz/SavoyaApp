const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const ts = require('typescript');

// Run the actual utility in fresh processes so each timezone is applied before
// any Date/Intl object is created, just as on devices with different settings.
const timezones = [
  'Europe/Moscow', 'UTC', 'America/Los_Angeles', 'Australia/Sydney',
  'Asia/Kathmandu', 'Pacific/Kiritimati', 'Pacific/Honolulu',
];

if (!process.argv.includes('--timezone-worker')) {
  for (const timezone of timezones) {
    const result = spawnSync(process.execPath, [__filename, '--timezone-worker'], {
      env: { ...process.env, TZ: timezone }, encoding: 'utf8',
    });
    assert.ifError(result.error);
    assert.equal(result.status, 0, `${timezone}\n${result.stdout}\n${result.stderr}`);
    process.stdout.write(result.stdout);
  }
  console.log(`Pass dates: all scenarios passed in ${timezones.length} timezones.`);
} else {
  const source = fs.readFileSync(path.resolve(__dirname, '../src/utils/date.ts'), 'utf8');
  const compiled = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
  }).outputText;
  const dates = {};
  new Function('exports', compiled)(dates);

  // Includes a leap day, year rollover and US/Australian DST transition days.
  const cases = [
    ['26.09.2026', '2026-09-26T20:59:59.999Z', '27.09.2026'],
    ['29.02.2028', '2028-02-29T20:59:59.999Z', '01.03.2028'],
    ['31.12.2026', '2026-12-31T20:59:59.999Z', '01.01.2027'],
    ['08.03.2026', '2026-03-08T20:59:59.999Z', '09.03.2026'],
    ['01.11.2026', '2026-11-01T20:59:59.999Z', '02.11.2026'],
    ['05.04.2026', '2026-04-05T20:59:59.999Z', '06.04.2026'],
    ['04.10.2026', '2026-10-04T20:59:59.999Z', '05.10.2026'],
  ];
  for (const [input, expectedIso, expectedDisplay] of cases) {
    const parsed = dates.parseDateInput(input);
    assert.ok(parsed, input);
    const original = parsed.getTime();
    assert.equal(dates.formatCalendarDate(parsed), input, 'manual date/picker round trip');
    assert.equal(dates.toIsoDate(parsed), expectedIso, 'API payload is Moscow end of day');
    const preview = dates.endOfMoscowDay(parsed);
    assert.equal(preview.toISOString(), expectedIso, 'preview and submitted expiry agree');
    assert.equal(dates.formatDateTime(preview), `${input}, 23:59`, 'actual expiry label');
    assert.equal(dates.formatDate(dates.addDays(preview, 1)), expectedDisplay, 'form +1 day');
    assert.equal(dates.formatDate(dates.addDays(expectedIso, 1)), expectedDisplay, 'card +1 day');
    assert.equal(parsed.getTime(), original, 'helpers do not modify picker state');

    // Calendar selections may preserve any local hour from the current value.
    // Neither midnight nor late evening may shift the chosen date in the form.
    for (const hour of [0, 12, 23]) {
      const selected = new Date(parsed);
      selected.setHours(hour, 30, 0, 0);
      const pickerInput = dates.formatCalendarDate(selected);
      assert.equal(pickerInput, input, 'picker selection stays on selected calendar day');
      assert.equal(dates.toIsoDate(dates.parseDateInput(pickerInput)), expectedIso);
    }
  }

  // A card timestamp close to Moscow midnight must not shift by an hour when
  // adding a day across the device's daylight-saving transition.
  for (const [instant, display] of [
    ['2026-03-07T21:30:00.000Z', '09.03.2026'],
    ['2026-10-31T20:30:00.000Z', '01.11.2026'],
    ['2026-04-04T20:30:00.000Z', '05.04.2026'],
    ['2026-10-03T21:30:00.000Z', '05.10.2026'],
  ]) {
    assert.equal(dates.formatDate(dates.addDays(instant, 1)), display, 'Moscow day across device DST');
  }
  for (const input of ['', '31.02.2026', '29.02.2027', '00.09.2026', '26.13.2026', '2026-09-26']) {
    assert.equal(dates.parseDateInput(input), null, `invalid input: ${input}`);
  }
  assert.equal(dates.formatDateInput('26092026'), '26.09.2026');
  assert.equal(dates.formatDate('2026-09-26T21:15:00Z'), '27.09.2026');
  assert.equal(dates.formatDateTime('2026-09-26T21:15:00Z'), '27.09.2026, 00:15');
  console.log(`${process.env.TZ}: 7 expiry/picker cases, 4 DST boundaries, validation and timestamp formatting passed.`);
}
