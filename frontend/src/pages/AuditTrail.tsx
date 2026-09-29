import { useLanguage } from "../i18n/LanguageProvider";
import { useAppData } from "../data/AppDataProvider";
import type { AuditEvent } from "../api/client";

function riskClass(risk: string) {
  if (risk.startsWith("L1")) return "l1";
  if (risk.startsWith("L2")) return "l2";
  return "l3";
}

function formatDateTime(iso: string) {
  return new Date(iso).toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}

export function AuditTrail() {
  const { t } = useLanguage();
  const { auditLog, loading, auditError: error } = useAppData();

  return (
    <section>
      <div className="page-head">
        <div className="eyebrow">{t("audit.eyebrow")}</div>
        <h1 className="page-title">{t("audit.title")}</h1>
        <p className="page-sub">{t("audit.sub")}</p>
      </div>

      {error && <p className="footnote" style={{ color: "var(--bad)" }}>{error}</p>}
      {!error && loading && auditLog.length === 0 && <p className="footnote">Loading audit trail…</p>}
      {!loading && !error && auditLog.length === 0 && (
        <div className="card" style={{ textAlign: "center", color: "var(--ink-dim)" }}>
          No AI-initiated actions yet.
        </div>
      )}

      {auditLog.map((entry) => (
        <AuditItem key={entry.id} entry={entry} />
      ))}
    </section>
  );
}

function AuditItem({ entry }: { entry: AuditEvent }) {
  return (
    <details className="audit-item">
      <summary>
        <span className={`badge ${riskClass(entry.risk_level)}`}>{entry.risk_level}</span>
        <strong>{entry.intent}</strong>
        <span className="audit-id">{entry.id.slice(0, 8)}</span>
        <span style={{ color: "var(--ink-faint)", fontSize: 12 }}>{formatDateTime(entry.created_at)}</span>
        <span className="chev">▶</span>
      </summary>
      <div className="audit-body">
        <div className="audit-grid">
          <Field k="Actor" v={entry.actor} />
          <Field k="Validation" v={entry.validation_result} />
          <Field k="Tool" v={entry.tool_name} />
          <Field k="Result" v={entry.result_summary} />
          <Field k="Correlation ID" v={entry.correlation_id} />
          <Field k="Confirmed" v={entry.confirmed ? "Yes, explicit" : "No"} />
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
