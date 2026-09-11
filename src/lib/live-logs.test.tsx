import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { ContainerLogViewer, logTail, logRequestFailure } from '../components/ContainerLogs';
import { FailureDetails } from '../components/FailureDetails';
import { liveLogsChinese } from '../i18n.live-logs';
import { translate } from '../i18n';
import { I18nContext } from '../i18n.context';

describe('live operator console', () => {
  it('stops retrying a rejected scope without hiding it as a network disconnect', () => {
    for (const cause of [Error('Select a valid experiment, preparation or run to view container logs.'), 'Error: Select a valid experiment, preparation or run to view container logs.']) {
      const result = logRequestFailure(cause);
      expect(result.retry).toBe(false);
      expect(result.message).toContain('rejected this log request');
      expect(result.message).not.toContain('reconnecting');
    }
    expect(logRequestFailure(Error('Not Found')).retry).toBe(false);
    expect(logRequestFailure(Error('Connection refused')).retry).toBe(true);
  });
  it('shows a specific pre-Agent failure without claiming model usage and escapes raw output', () => {
    const html = renderToStaticMarkup(<I18nContext.Provider value={{ locale: 'zh-CN', setLocale: () => {}, t: (key) => translate('zh-CN', key) }}><FailureDetails diagnostic={{ logSessionId: 'fixture', stage: 'Fetch frozen Git baseline', category: 'repository', agentStarted: false, summary: '<script>bad()</script>', hint: 'Check repository access, the frozen baseline commit and the working directory permissions.' }} onLogs={() => {}} /></I18nContext.Provider>);
    expect(html).toContain('&lt;script&gt;');
    expect(html).not.toContain('<script>');
    expect(html).toContain(translate('zh-CN', 'Fetch frozen Git baseline'));
    expect(html).toContain(translate('zh-CN', 'View complete execution log'));
  });
  it('bounds text without leaving a broken surrogate pair', () => {
    expect(logTail('🙂' + 'x'.repeat(199999))).toBe('x'.repeat(199999));
    expect(logTail('a'.repeat(300000)).length).toBe(200000);
    expect(logTail('中文🙂')).toBe('中文🙂');
  });
  it('provides Chinese translations for every live-console label', () => {
    for (const [key, value] of Object.entries(liveLogsChinese)) expect(translate('zh-CN', key)).toBe(value);
  });
  it('renders a read-only console without execution or retry controls', () => {
    const html = renderToStaticMarkup(<I18nContext.Provider value={{ locale: 'en', setLocale: () => {}, t: (key) => key }}><ContainerLogViewer scope={{ experimentId: 'fixture' }} /></I18nContext.Provider>);
    expect(html).toContain('live-container-output');
    expect(html).toContain('type="checkbox"');
    expect(html).not.toContain('type="submit"');
    expect(html).not.toContain('textarea');
  });
});
