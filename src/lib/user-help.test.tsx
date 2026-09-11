import { expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { UserHelpDialog, helpTopics } from '../components/UserHelpDialog';
import { Topbar } from '../components/Topbar';
import { I18nContext } from '../i18n.context';
import { translate } from '../i18n';
import { userHelpChinese } from '../i18n.user-help';

it.each(['en', 'zh-CN'] as const)('provides local, task-oriented help in %s', (locale) => {
  const value = { locale, setLocale() {}, t: (key: string) => translate(locale, key) };
  const html = renderToStaticMarkup(<I18nContext.Provider value={value}><UserHelpDialog onClose={() => {}} /></I18nContext.Provider>);
  expect(html).toContain('<dialog');
  for (const topic of helpTopics) for (const text of topic) expect(html).toContain(translate(locale, text).replaceAll('&', '&amp;'));
  const topbar = renderToStaticMarkup(<I18nContext.Provider value={value}><Topbar runtime="desktop" /></I18nContext.Provider>);
  expect(topbar).toMatch(new RegExp(`<button[^>]+aria-label="${translate(locale, 'Help')}"`));
  expect(topbar).not.toContain('github.com');
});

it('translates every help sentence without changing the English fallback', () => {
  for (const [key, value] of Object.entries(userHelpChinese)) {
    expect(translate('zh-CN', key)).toBe(value);
    expect(translate('en', key)).toBe(key);
    expect(value).not.toBe(key);
  }
});
