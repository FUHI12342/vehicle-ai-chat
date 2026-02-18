"use client";

import { useState, useEffect } from "react";
import { getProviders, setActiveProvider } from "@/lib/api";
import type { ProviderInfo } from "@/lib/types";
import { ja } from "@/i18n/ja";

export function ProviderSelector() {
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [active, setActive] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadProviders();
  }, []);

  async function loadProviders() {
    try {
      const data = await getProviders();
      setProviders(data.providers);
      setActive(data.active);
    } catch {
      // API not available
    } finally {
      setLoading(false);
    }
  }

  async function handleSelect(name: string) {
    try {
      await setActiveProvider(name);
      setActive(name);
    } catch (e) {
      alert(e instanceof Error ? e.message : "Failed to switch provider");
    }
  }

  if (loading) return <div className="text-sm text-gray-400">読み込み中...</div>;

  return (
    <div className="bg-gray-50 rounded-lg p-3 border border-gray-200">
      <p className="text-xs font-medium text-gray-500 mb-2">{ja.provider.title}</p>
      <div className="flex flex-wrap gap-2">
        {providers.map((p) => (
          <button
            key={p.name}
            onClick={() => p.is_configured && handleSelect(p.name)}
            disabled={!p.is_configured}
            className={`px-3 py-1.5 text-xs rounded-full border transition-colors ${
              p.name === active
                ? "bg-blue-600 text-white border-blue-600"
                : p.is_configured
                ? "bg-white text-gray-700 border-gray-300 hover:border-blue-400"
                : "bg-gray-100 text-gray-400 border-gray-200 cursor-not-allowed"
            }`}
          >
            {p.display_name}
            {!p.is_configured && ` (${ja.provider.notConfigured})`}
            {p.name === active && ` - ${ja.provider.active}`}
          </button>
        ))}
      </div>
    </div>
  );
}
