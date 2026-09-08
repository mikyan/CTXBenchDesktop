import { useI18n } from "../i18n";

/** Ordinary navigation buttons retain native keyboard behavior; inactive forms stay mounted. */
export function SectionNav<T extends string>({ label, items, value, onChange, vertical = false }: {
  label: string; items: readonly { id: T; label: string; group?: string }[];
  value: T; onChange: (id: T) => void; vertical?: boolean;
}) {
  const { t } = useI18n();
  return <nav className={`section-nav ${vertical ? "vertical" : "horizontal"}`} aria-label={t(label)}>
    {items.map((item, index) => <div key={item.id}>
      {vertical && item.group && item.group !== items[index - 1]?.group && <p className="section-nav-group">{t(item.group)}</p>}
      <button type="button" aria-current={value === item.id ? "page" : undefined} className={value === item.id ? "selected" : ""} onClick={() => onChange(item.id)}>{t(item.label)}</button>
    </div>)}
  </nav>;
}
