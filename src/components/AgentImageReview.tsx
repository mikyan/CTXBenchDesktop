import type { TaskSummary } from '../domain/types';
import { useI18n } from '../i18n';

export function AgentImageReview({ tasks, image, projectEnvironment, generatesContext }: {
  tasks: TaskSummary[]; image: string; projectEnvironment: boolean; generatesContext: boolean;
}) {
  const { t } = useI18n();
  return <>
    <fieldset><legend>{t('Coding Agent images by task')}</legend><dl className="review-grid">
      {tasks.map(task => <div key={task.id}><dt>{task.id}</dt><dd><code>{task.customAgentImage || image}</code><p>{t(task.customAgentImage
        ? 'Case override — uses the custom command and image.'
        : projectEnvironment ? 'Experiment base — combined with the project environment during preparation.' : 'Experiment default — used without project dependency composition.')}</p></dd></div>)}
    </dl>
    {tasks.some(task => task.customAgentImage) && <p>{t('Custom commands retain their own model configuration unless they explicitly use the supplied model variables. The experiment default does not replace their image or command.')}</p>}
    {projectEnvironment && tasks.some(task => !task.customAgentImage) && <p>{t('Prepared image digests are available after preparation. The addresses above identify the selected base images, not unbuilt image digests.')}</p>}
    </fieldset>
    {generatesContext && <p>{t('Knowledge builder base image')}: <code>{image}</code> · {t(projectEnvironment ? 'Prepared project environment' : 'Agent image as-is')}</p>}
  </>;
}
