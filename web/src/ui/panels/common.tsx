import type { ReactNode } from "react";
import { t } from "../../i18n/t";
import { useStore } from "../../state/store";

/** Show a message when the plan data of the selected scenario does not exist. */
export function PlanGate({ children }: { children: ReactNode }) {
  const status = useStore((s) => s.planStatus);
  const plan = useStore((s) => s.planScenario?.plan);
  if (status === "loading" || status === "idle") return <p className="note">{t("common.loading")}</p>;
  if (!plan) return <p className="note">{t("common.noPlan")}</p>;
  return <>{children}</>;
}

/** A section with a title. */
export function Section({ title, children, right }: { title: string; children: ReactNode; right?: ReactNode }) {
  return (
    <section className="section">
      <div style={{ display: "flex", alignItems: "baseline" }}>
        <h3 style={{ flex: 1 }}>{title}</h3>
        {right}
      </div>
      {children}
    </section>
  );
}

