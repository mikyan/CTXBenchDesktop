import { useI18n } from '../i18n';
import { Modal } from './Dialogs';
import { ExternalLink } from './ExternalLink';

export const helpTopics = [
  ['Prepare the tools, then create one case', 'Settings → Image adaptation', 'An image contains the tools and dependencies needed by your Agent or tests. Pull an existing image or follow Build your image step by step. A successful image build does not mean a benchmark has passed.'],
  ['Describe one task and how to check it', 'Evaluation cases → Create evaluation case', 'Choose a repository and the full commit before the fix, describe the task, and provide a separate test command. Select your Agent image and launch command under Task and tests if you are not using Pi. Hidden tests and reference fixes belong only in the evaluator fields.'],
  ['Run and inspect the result', 'Evaluation cases → New experiment', 'Select the model settings, runtime variable names and comparison groups. A custom Agent keeps its own model unless your command uses the supplied model variables. Inspect Results & evidence and the full logs. Only the independent test evaluator determines whether the case passed; Agent exit 0 alone does not.'],
] as const;

export function UserHelpDialog({ onClose }: { onClose: () => void }) {
  const { t } = useI18n();
  return <Modal title={t('User guide · start with one case')} onClose={onClose}>
    <p className="wizard-notice">{t('This guide stays in the app and follows your interface language. You do not need to read the source code or copy files into Docker to get started.')}</p>
    <ol className="user-help-steps">{helpTopics.map(([title, path, description]) => <li key={title}>
      <h3>{t(title)}</h3><p><strong>{t(path)}</strong></p><p>{t(description)}</p>
    </li>)}</ol>
    <details><summary>{t('What are cases, datasets, experiments and knowledge?')}</summary>
      <dl className="user-help-glossary">
        <dt>{t('Evaluation cases')}</dt><dd>{t('One repository task with a fixed starting commit, a prompt, an Agent and independent grading rules. It can run on its own.')}</dd>
        <dt>{t('Datasets')}</dt><dd>{t('A reusable selection of saved cases. Combine existing cases here when you want to run them together.')}</dd>
        <dt>{t('Experiments')}</dt><dd>{t('A saved run plan and its results. Starting an experiment freezes the selected case definitions, so later edits do not rewrite old results.')}</dd>
        <dt>{t('Knowledge')}</dt><dd>{t('Optional frozen context files beside the repository code. Generate them once from the starting commit or import your own; they can be reused across runs. The Agent decides whether to use them.')}</dd>
      </dl>
    </details>
    <details><summary>{t('Where do API keys and logs go?')}</summary>
      <p>{t('Settings → Model credentials saves runtime variables. Select only the variable names needed by an experiment. Never put keys in an image recipe, uploaded configuration, task prompt or launch command. Custom Agent token usage may be unknown; this does not prevent testing.')}</p>
      <p>{t('When a run fails, open its details and full logs, including preparation and evaluator logs. An environment failure before the Agent starts is not a failed code solution.')}</p>
    </details>
    <p><ExternalLink destination="help">{t('Project documentation on GitHub (advanced)')}</ExternalLink></p>
  </Modal>;
}
