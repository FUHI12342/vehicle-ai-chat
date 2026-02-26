import type { UrgencyInfo } from "@/lib/types";
import { URGENCY_COLORS } from "@/lib/constants";
import { ja } from "@/i18n/ja";

interface UrgencyAlertProps {
  urgency: UrgencyInfo;
}

export function UrgencyAlert({ urgency }: UrgencyAlertProps) {
  const colors = URGENCY_COLORS[urgency.level];
  const visitLabel = urgency.visit_urgency
    ? ja.visitUrgency[urgency.visit_urgency]
    : null;

  return (
    <div
      className={`${colors.bg} ${colors.border} border rounded-xl p-4 animate-fade-in`}
    >
      <div className="flex items-center gap-2 mb-2">
        {(urgency.level === "high" || urgency.level === "critical") && (
          <svg className="w-5 h-5 text-red-500" fill="currentColor" viewBox="0 0 20 20">
            <path
              fillRule="evenodd"
              d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z"
              clipRule="evenodd"
            />
          </svg>
        )}
        <span className={`font-bold ${colors.text}`}>
          緊急度: {colors.label}
        </span>
      </div>

      {urgency.can_drive === false && (
        <p className="text-red-700 font-bold text-sm mb-2">
          🚨 運転を中止してください
        </p>
      )}

      {visitLabel && (
        <p className={`text-sm font-medium ${colors.text} mb-2`}>
          🏥 {visitLabel}
        </p>
      )}

      {urgency.reasons.length > 0 && (
        <ul className={`text-sm ${colors.text} space-y-1 mb-3`}>
          {urgency.reasons.map((reason, i) => (
            <li key={i}>・{reason}</li>
          ))}
        </ul>
      )}

      {urgency.requires_visit && (
        <div className="mt-3 pt-3 border-t border-current/10">
          <p className={`text-sm font-medium ${colors.text}`}>
            ディーラーへの来店をお勧めします
          </p>
        </div>
      )}
    </div>
  );
}
