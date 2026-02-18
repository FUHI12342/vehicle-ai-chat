export const API_BASE = "/api";

export const URGENCY_COLORS = {
  low: { bg: "bg-green-50", border: "border-green-300", text: "text-green-800", label: "低" },
  medium: { bg: "bg-yellow-50", border: "border-yellow-300", text: "text-yellow-800", label: "中" },
  high: { bg: "bg-orange-50", border: "border-orange-400", text: "text-orange-800", label: "高" },
  critical: { bg: "bg-red-50", border: "border-red-400", text: "text-red-800", label: "緊急" },
} as const;
