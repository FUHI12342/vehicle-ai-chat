"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { ja } from "@/i18n/ja";
import { architectureDiagram } from "@/lib/architecture-diagram";

interface Props {
  isOpen: boolean;
  onClose: () => void;
}

export function ArchitectureDiagramModal({ isOpen, onClose }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);

  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    },
    [onClose]
  );

  useEffect(() => {
    if (!isOpen) return;

    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, handleKeyDown]);

  useEffect(() => {
    if (!isOpen || !containerRef.current) return;

    let cancelled = false;

    (async () => {
      try {
        const mermaid = (await import("mermaid")).default;
        mermaid.initialize({
          startOnLoad: false,
          theme: "default",
          securityLevel: "loose",
          flowchart: { useMaxWidth: true, htmlLabels: true, curve: "basis" },
        });

        const id = `arch-${Date.now()}`;
        const { svg } = await mermaid.render(id, architectureDiagram);

        if (!cancelled && containerRef.current) {
          containerRef.current.innerHTML = svg;
          setError(null);
        }
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "図の描画に失敗しました");
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [isOpen]);

  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="relative bg-white rounded-2xl shadow-xl w-[95vw] h-[90vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
          <h2 className="text-lg font-bold text-gray-900">
            {ja.architecture.title}
          </h2>
          <button
            onClick={onClose}
            className="text-sm text-gray-500 hover:text-gray-700 px-3 py-1 rounded-lg hover:bg-gray-100 transition-colors"
          >
            {ja.architecture.close}
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-auto p-6">
          {error ? (
            <div className="text-red-600 text-sm text-center py-8">
              {error}
            </div>
          ) : (
            <div
              ref={containerRef}
              className="flex items-start justify-center min-h-full [&>svg]:max-w-full"
            />
          )}
        </div>
      </div>
    </div>
  );
}
