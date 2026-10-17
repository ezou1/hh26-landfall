import { t } from "../i18n/t";
import { useStore } from "../state/store";

/** The drawer that lists the model assumptions from meta.json. */
export function AssumptionsDrawer() {
  const open = useStore((s) => s.assumptionsOpen);
  const meta = useStore((s) => s.meta);
  const set = useStore((s) => s.set);
  const fallbackItems = useStore((s) => s.fallbackItems);
  const fallbackUrls = useStore((s) => s.fallbackUrls);
  if (!open) return null;
  const list = meta?.assumptions ?? [];
  return (
    <div className="drawer" role="dialog" aria-label={t("assumptions.title")}>
      <div style={{ display: "flex", alignItems: "center" }}>
        <h3 style={{ flex: 1, margin: 0 }}>{t("assumptions.title")}</h3>
        <button className="btn" onClick={() => set({ assumptionsOpen: false })}>
          {t("common.close")}
        </button>
      </div>
      <p className="muted">{t("assumptions.intro")}</p>
      {list.length === 0 && <p className="muted">{t("assumptions.none")}</p>}
      <dl>
        {list.map((a) => (
          <div key={a.key}>
            <dt>
              {a.key} = {String(a.value)} {a.unit ?? ""}
            </dt>
            <dd>{a.text ?? ""}</dd>
          </div>
        ))}
      </dl>
      {(fallbackItems.length > 0 || fallbackUrls.length > 0) && (
        <>
          <h3 style={{ marginTop: 18 }}>{t("assumptions.fallback")}</h3>
          <ul>
            {fallbackItems.map((f) => (
              <li key={f}>{f}</li>
            ))}
          </ul>
          <p className="muted">{t("assumptions.fallbackFiles")}</p>
          <ul className="muted">
            {fallbackUrls.map((u) => (
              <li key={u}>{u}</li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
