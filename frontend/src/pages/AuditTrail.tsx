import { useLanguage } from "../i18n/LanguageProvider";
import { useAppData, type AuditEntry } from "../data/AppDataProvider";

function riskClass(risk: string) {
  if (risk.startsWith("L1")) return "l1";
  if (risk.startsWith("L2")) return "l2";
  return "l3";
}

export function AuditTrail() {
  const { t } = useLanguage();
  const { auditLog } = useAppData();

  return (
    <section>
      <div className="page-head">
        <div className="eyebrow">{t("audit.eyebrow")}</div>
        <h1 className="page-title">{t("audit.title")}</h1>
        <p className="page-sub">{t("audit.sub")}</p>
      </div>

      {auditLog.map((entry) => (
        <AuditItem key={entry.id} entry={entry} />
      ))}
    </section>
  );
}

function AuditItem({ entry }: { entry: AuditEntry }) {
  return (
    <details className="audit-item">
      <summary>
        <span className={`badge ${riskClass(entry.risk)}`}>{entry.risk}</span>
        <strong>{entry.intent}</strong>
        <span className="audit-id">{entry.id}</span>
        <span style={{ color: "var(--ink-faint)", fontSize: 12 }}>{entry.time}</span>
        <span className="chev">▶</span>
      </summary>
      <div className="audit-body">
        <div className="audit-grid">
          <Field k="Actor" v={entry.actor} />
          <Field k="Context" v={entry.context} />
          <Field k="Tool" v={entry.tool} />
          <Field k="Result" v={entry.result} />
          <Field k="Correlation ID" v={entry.corr} />
          <Field k="Confirmed" v={entry.risk === "L1 Read" ? "n/a — read only" : "Yes, explicit"} />
        </div>
      </div>
    </details>
  );
}

function Field({ k, v }: { k: string; v: string }) {
  return (
    <div>
      <span>{k}</span>
      <span>{v}</span>
    </div>
  );
}
