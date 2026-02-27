"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { ja } from "@/i18n/ja";
import { architectureDiagram } from "@/lib/architecture-diagram";

interface Props {
  isOpen: boolean;
  onClose: () => void;
}

const ZOOM_MIN = 0.3;
const ZOOM_MAX = 3.0;
const ZOOM_STEP = 0.15;

export function ArchitectureDiagramModal({ isOpen, onClose }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);
  const [zoom, setZoom] = useState(1);

  // Reset zoom when modal opens
  useEffect(() => {
    if (isOpen) setZoom(1);
  }, [isOpen]);

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

  // Mouse wheel zoom
  const handleWheel = useCallback((e: WheelEvent) => {
    if (e.ctrlKey || e.metaKey) {
      e.preventDefault();
      setZoom((prev) => {
        const delta = e.deltaY > 0 ? -ZOOM_STEP : ZOOM_STEP;
        return Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, prev + delta));
      });
    }
  }, []);

  useEffect(() => {
    const el = scrollRef.current;
    if (!isOpen || !el) return;
    el.addEventListener("wheel", handleWheel, { passive: false });
    return () => el.removeEventListener("wheel", handleWheel);
  }, [isOpen, handleWheel]);

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
          flowchart: { useMaxWidth: false, htmlLabels: true, curve: "basis" },
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

  const zoomIn = () => setZoom((z) => Math.min(ZOOM_MAX, z + ZOOM_STEP));
  const zoomOut = () => setZoom((z) => Math.max(ZOOM_MIN, z - ZOOM_STEP));
  const zoomReset = () => setZoom(1);
  const zoomPercent = Math.round(zoom * 100);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="relative bg-white rounded-2xl shadow-xl w-[95vw] h-[90vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-3 border-b border-gray-200">
          <h2 className="text-lg font-bold text-gray-900">
            {ja.architecture.title}
          </h2>
          <div className="flex items-center gap-2">
            {/* Zoom controls */}
            <div className="flex items-center gap-1 bg-gray-100 rounded-lg px-2 py-1">
              <button
                onClick={zoomOut}
                disabled={zoom <= ZOOM_MIN}
                className="w-7 h-7 flex items-center justify-center rounded text-gray-600 hover:bg-gray-200 disabled:opacity-30 disabled:hover:bg-transparent text-sm font-bold"
                title="縮小"
              >
                −
              </button>
              <button
                onClick={zoomReset}
                className="px-2 h-7 text-xs text-gray-600 hover:bg-gray-200 rounded min-w-[3rem] text-center"
                title="リセット"
              >
                {zoomPercent}%
              </button>
              <button
                onClick={zoomIn}
                disabled={zoom >= ZOOM_MAX}
                className="w-7 h-7 flex items-center justify-center rounded text-gray-600 hover:bg-gray-200 disabled:opacity-30 disabled:hover:bg-transparent text-sm font-bold"
                title="拡大"
              >
                +
              </button>
            </div>
            <span className="text-xs text-gray-400 hidden sm:inline">Cmd+スクロールでも拡大縮小</span>
            <button
              onClick={onClose}
              className="text-sm text-gray-500 hover:text-gray-700 px-3 py-1 rounded-lg hover:bg-gray-100 transition-colors ml-2"
            >
              {ja.architecture.close}
            </button>
          </div>
        </div>

        {/* Body */}
        <div ref={scrollRef} className="flex-1 overflow-auto p-6 cursor-grab active:cursor-grabbing">
          {error ? (
            <div className="text-red-600 text-sm text-center py-8">
              {error}
            </div>
          ) : (
            <div
              ref={containerRef}
              className="inline-block origin-top-left transition-transform duration-100"
              style={{ transform: `scale(${zoom})` }}
            />
          )}
        </div>
      </div>
    </div>
  );
}
