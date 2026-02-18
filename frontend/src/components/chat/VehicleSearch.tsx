"use client";

import { useState, useCallback } from "react";
import { searchVehicles } from "@/lib/api";
import type { VehicleMatch } from "@/lib/types";
import { ja } from "@/i18n/ja";

interface VehicleSearchProps {
  onSelect: (vehicleId: string, displayName: string) => void;
  disabled?: boolean;
}

export function VehicleSearch({ onSelect, disabled }: VehicleSearchProps) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<VehicleMatch[]>([]);
  const [searching, setSearching] = useState(false);
  const [searched, setSearched] = useState(false);

  const handleSearch = useCallback(async (q: string) => {
    setQuery(q);
    if (q.trim().length < 1) {
      setResults([]);
      setSearched(false);
      return;
    }
    setSearching(true);
    try {
      const matches = await searchVehicles(q.trim());
      setResults(matches);
      setSearched(true);
    } catch {
      setResults([]);
    } finally {
      setSearching(false);
    }
  }, []);

  return (
    <div className="space-y-3 animate-fade-in">
      <div className="relative">
        <input
          type="text"
          value={query}
          onChange={(e) => handleSearch(e.target.value)}
          placeholder={ja.vehicle.searchPlaceholder}
          disabled={disabled}
          className="w-full px-4 py-3 border border-gray-300 rounded-xl focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent text-sm pr-10"
        />
        <svg
          className="absolute right-3 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-400"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
          />
        </svg>
      </div>

      {searching && (
        <p className="text-sm text-gray-400">{ja.vehicle.searching}</p>
      )}

      {searched && results.length === 0 && !searching && (
        <p className="text-sm text-gray-400">{ja.vehicle.noResults}</p>
      )}

      {results.length > 0 && (
        <div className="space-y-2 max-h-64 overflow-y-auto">
          {results.map((match) => {
            const v = match.vehicle;
            const displayName = `${v.year}年 ${v.make} ${v.model} ${v.trim}`;
            return (
              <button
                key={v.id}
                onClick={() => onSelect(v.id, displayName)}
                disabled={disabled}
                className="w-full text-left px-4 py-3 bg-white border border-gray-200 rounded-xl hover:border-blue-400 hover:bg-blue-50 transition-colors"
              >
                <div className="font-medium text-sm text-gray-900">
                  {v.make} {v.model}
                </div>
                <div className="text-xs text-gray-500 mt-0.5">
                  {v.year}年式 {v.trim}
                  {v.manual_available && " | マニュアルあり"}
                </div>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
