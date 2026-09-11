import { expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { InfrastructureSetup } from '../components/InfrastructureSetup';
import { IsolationNotice } from '../components/IsolationNotice';
import { I18nContext } from '../i18n.context';
import { translate } from '../i18n';

it('localizes production-port rejection without obscuring the port', () => {
  const message = 'Debug isolation cannot use the production service port 48173. Choose another local port; no service request was sent.';
  expect(translate('en', message)).toBe(message);
  expect(translate('zh-CN', message)).not.toBe(message);
  expect(translate('zh-CN', message)).toContain('48173');
});

it.each(['en', 'zh-CN'] as const)('keeps an explicit isolation notice and removes production controls in %s', (locale) => {
  const html = renderToStaticMarkup(<I18nContext.Provider value={{ locale, setLocale() {}, t: (key, values) => translate(locale, key, values) }}>
    <IsolationNotice connection={{ isolated: true, baseUrl: 'http://127.0.0.1:48174/v1' }} />
    <InfrastructureSetup isolated view="images" distribution="Ubuntu" diagnosing={false} onDistribution={() => {}} onDiagnose={() => {}} onBusy={() => {}} />
  </I18nContext.Provider>);
  expect(html).toContain('http://127.0.0.1:48174/v1');
  expect(html).toContain(translate(locale, 'Isolated acceptance instance — not your production workspace'));
  expect(html).toContain(translate(locale, 'Package customized Docker images'));
  expect(html).not.toContain(translate(locale, 'Start worker'));
  expect(html).not.toContain(translate(locale, 'Stop worker'));
  expect(html).not.toContain(translate(locale, 'Build images'));
  expect(html).not.toContain(translate(locale, 'Select offline images ZIP'));
});

it('does not mark normal connections as isolated and surfaces malformed native configuration', () => {
  const value = { locale: 'en' as const, setLocale() {}, t: (key: string) => key };
  expect(renderToStaticMarkup(<I18nContext.Provider value={value}><IsolationNotice connection={{ isolated: false, baseUrl: 'http://127.0.0.1:48173/v1' }} /></I18nContext.Provider>)).toBe('');
  expect(renderToStaticMarkup(<I18nContext.Provider value={value}><IsolationNotice connection={{ isolated: true, baseUrl: '', error: 'Invalid port' }} /></I18nContext.Provider>)).toContain('role="alert"');
});
