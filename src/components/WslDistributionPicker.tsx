import { useEffect, useRef, useState } from "react";
import { RefreshCw } from "lucide-react";
import { useI18n } from "../i18n";
import { listWslDistributions } from "../lib/desktop";
import { chooseDistribution, type WslInventory } from "../lib/wsl";

export function WslDistributionPicker({ value, onChange, disabled = false }: {
  value: string; onChange: (name: string) => void; disabled?: boolean;
}) {
  const { t } = useI18n();
  const [inventory, setInventory] = useState<WslInventory>();
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [refreshKey, setRefreshKey] = useState(0);
  const latest = useRef({ value, onChange });
  latest.current = { value, onChange };
  const editRevision = useRef(0);

  useEffect(() => {
    let alive = true;
    const revision = editRevision.current;
    setLoading(true);
    setError("");
    void listWslDistributions().then((result) => {
      if (!alive) return;
      setInventory(result);
      // A late response must not replace a name the user is still typing.
      if (revision === editRevision.current) {
        const chosen = chooseDistribution(latest.current.value, result);
        if (chosen !== latest.current.value) latest.current.onChange(chosen);
      }
    }).catch((failure: unknown) => {
      if (!alive) return;
      setInventory(undefined);
      setError(failure instanceof Error ? failure.message : String(failure));
    }).finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [refreshKey]);

  const change = (name: string) => { editRevision.current++; onChange(name); };
  const matching = inventory?.distributions.find((item) => item.name.toLowerCase() === value.trim().toLowerCase());
  return <div className="wsl-picker">
    <div className="wsl-picker-list">
      <label>{t("Installed WSL distributions")}
        <select value={matching?.name ?? ""} disabled={disabled || loading || !inventory?.distributions.length} onChange={(event) => change(event.target.value)}>
          <option value="" disabled>{loading ? t("Detecting WSL distributions…") : t("Select a distribution or enter its name below")}</option>
          {inventory?.distributions.map((item) => <option key={item.name} value={item.name}>
            {item.name} · WSL {item.version}{item.isDefault ? ` · ${t("System default")}` : ""}
          </option>)}
        </select>
      </label>
      <button type="button" className="button secondary" disabled={disabled || loading} onClick={() => setRefreshKey((key) => key + 1)}>
        <RefreshCw size={16} className={loading ? "spin" : ""} />{t("Refresh distributions")}
      </button>
    </div>
    <label>{t("Distribution name (editable)")}
      <input value={value} disabled={disabled} placeholder="Ubuntu-24.04" autoComplete="off" spellCheck={false} onChange={(event) => change(event.target.value)} />
    </label>
    <p>{t("Your selection is remembered. Without a saved selection, a WSL 2 distribution is preferred. You can also enter an exact name manually.")}</p>
    {error && <p role="alert">{t("Could not list WSL distributions. Manual input is still available.")} {t(error)}</p>}
    {!loading && inventory?.distributions.length === 0 && <p role="status">{t("No WSL distributions found. Install a distribution, then refresh.")}</p>}
    {!loading && inventory && value.trim() && !matching && <p role="status">{t("This name is not in the detected list. Check its spelling or refresh after installing a distribution.")}</p>}
    {matching?.version === 1 && <p role="status">{t("Select a WSL 2 distribution. The selected distribution uses WSL 1.")}</p>}
  </div>;
}
