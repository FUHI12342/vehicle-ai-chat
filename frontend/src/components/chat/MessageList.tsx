"use client";

import { useEffect, useRef } from "react";
import type { ChatMessage } from "@/lib/types";
import { MessageBubble } from "./MessageBubble";
import { UrgencyAlert } from "./UrgencyAlert";

interface MessageListProps {
  messages: ChatMessage[];
  currentStep?: string;
  onRewind?: (turn: number) => void;
}

export function MessageList({ messages, currentStep, onRewind }: MessageListProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Find the last user message index for rewind logic
  const lastUserIdx = (() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i].role === "user") return i;
    }
    return -1;
  })();

  return (
    <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
      {messages.map((msg, idx) => {
        // Show rewind button on user messages in diagnosing step, except the latest one
        const showRewind =
          currentStep === "diagnosing" &&
          msg.role === "user" &&
          msg.diagnosticTurn != null &&
          idx !== lastUserIdx;

        return (
          <div key={msg.id} className="space-y-2">
            <MessageBubble
              message={msg}
              onRewind={onRewind}
              showRewind={showRewind}
            />
            {msg.urgency && msg.urgency.level !== "low" && (
              <div className="max-w-[90%]">
                <UrgencyAlert urgency={msg.urgency} />
              </div>
            )}
            {msg.manualCoverage === "not_covered" && (
              <div className="max-w-[90%]">
                <div className="inline-block bg-yellow-100 text-yellow-800 border border-yellow-300 rounded-lg px-3 py-1.5 text-xs font-medium">
                  ⚠ マニュアル記載外 — 想定外の不具合の可能性があります
                </div>
              </div>
            )}
            {msg.manualCoverage === "partially_covered" && (
              <div className="max-w-[90%]">
                <div className="inline-block bg-gray-100 text-gray-600 border border-gray-300 rounded-lg px-3 py-1.5 text-xs font-medium">
                  マニュアルに完全一致する情報はありません
                </div>
              </div>
            )}
            {msg.rag_sources && msg.rag_sources.length > 0 && (
              <div className="max-w-[90%]">
                <details className="text-xs text-gray-400">
                  <summary className="cursor-pointer hover:text-gray-600">
                    参照元 ({msg.rag_sources.length}件)
                  </summary>
                  <div className="mt-1 space-y-1 pl-2 border-l-2 border-gray-200">
                    {msg.rag_sources.map((src, i) => (
                      <div key={i} className="text-gray-500">
                        <span className="font-medium">
                          {src.section || `p.${src.page}`}
                        </span>
                        {" - "}
                        {src.content.substring(0, 100)}...
                      </div>
                    ))}
                  </div>
                </details>
              </div>
            )}
          </div>
        );
      })}
      <div ref={bottomRef} />
    </div>
  );
}
