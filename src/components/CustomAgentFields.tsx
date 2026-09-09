import { useI18n } from '../i18n';
import type { TaskDraft } from '../lib/dataset-authoring';
import { RemoteImagePull } from './RemoteImagePull';

export function CustomAgentFields({ value, onChange }: { value: TaskDraft['agent']; onChange: (value: TaskDraft['agent']) => void }) {
  const { t } = useI18n();
  return <fieldset className="custom-agent-fields"><legend>{t('Coding Agent · separate from test commands')}</legend>
    <label>{t('Agent launch mode')}<select value={value ? 'command' : 'default'} onChange={(e) => onChange(e.target.value === 'default' ? undefined : { image: '', commandMode: 'shell', command: 'company-agent --model "$CTXBENCH_MODEL" --prompt "$(cat "$CTXBENCH_PROMPT_FILE")"' })}>
      <option value="default">{t('Use the experiment Agent (Pi by default)')}</option><option value="command">{t('Run my own Agent command')}</option>
    </select></label>
    {value && <>
      <p className="wizard-notice">{t('This overrides coding only. Knowledge generation and constraint roles keep their experiment configuration. The image is used as-is: install your Agent, python3, git and /bin/sh; do not include answers, hidden tests or credentials.')}</p>
      <label>{t('Custom Agent image')}<input value={value.image} placeholder="registry.company.example/team/agent:1.0" onChange={(e) => onChange({ ...value, image: e.target.value })} /></label>
      <RemoteImagePull initialImage={value.image} onInstalled={(image) => onChange({ ...value, image })} compact />
      <label>{t('Agent command format')}<select value={value.commandMode} onChange={(e) => {
        if (e.target.value === 'argv') onChange({ ...value, commandMode: 'argv', command: JSON.stringify(['/bin/sh', '-eu', '-c', value.command]) });
        else { try { const args = JSON.parse(value.command) as string[]; onChange({ ...value, commandMode: 'shell', command: args.map((arg) => "'" + arg.replaceAll("'", "'\"'\"'") + "'").join(' ') }); } catch { onChange({ ...value, commandMode: 'shell' }); } }
      }}><option value="shell">{t('Shell script (/bin/sh)')}</option><option value="argv">{t('Argument array (JSON)')}</option></select></label>
      <label>{t('Agent startup command')}<textarea rows={5} spellCheck={false} value={value.command} onChange={(e) => onChange({ ...value, command: e.target.value })} /></label>
      <p>{t('The exact step prompt is in CTXBENCH_PROMPT_FILE. Read it as a quoted argument or redirect it to stdin. Commands run in /workspace and must exit when finished. Exit 0 completes coding; only the separate evaluator decides PASS.')}</p>
      <details><summary>{t('Custom Agent configuration contract')}</summary>
        <p>{t('CTXBENCH_MODEL, CTXBENCH_PROVIDER, CTXBENCH_THINKING and CTXBENCH_MAX_TOKENS expose the selected settings. Your command must apply them; the tool cannot verify an arbitrary CLI model or enforce its token limit. Use runtime environment variables for API keys, not command literals.')}</p>
        <p>{t('Missing token usage does not block custom commands or affect grading. These commands bypass shared token accounting; only metered roles remain budget-protected. Token totals and allowances exclude custom commands, not their actual consumption. Configure spending limits in your Agent or Provider.')}</p>
        <p>{t('Container time, CPU, memory and network limits still apply. Each workflow step starts a new command with its own prompt. Put custom Agent arguments in this command, not in global Pi startup arguments.')}</p>
        <p>{t('Install dependencies and non-secret defaults under /opt or /etc. /workspace is replaced by the clean baseline. Use a writable HOME for UID 10001; otherwise a temporary HOME is used. Image ENTRYPOINT and CMD are replaced by the command adapter.')}</p>
      </details>
    </>}
  </fieldset>;
}
