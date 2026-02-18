"use client";

import { useEffect, useRef } from "react";
import type { ChatMessage } from "@/lib/types";
import { MessageBubble } from "./MessageBubble";
import { UrgencyAlert } from "./UrgencyAlert";

interface MessageListProps {
  messages: ChatMessage[];
}

export function MessageList({ messages }: MessageListProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  return (
    <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
      {messages.map((msg) => (
        <div key={msg.id} className="space-y-2">
          <MessageBubble message={msg} />
          {msg.urgency && msg.urgency.level !== "low" && (
            <div className="max-w-[80%]">
              <UrgencyAlert urgency={msg.urgency} />
            </div>
          )}
          {msg.rag_sources && msg.rag_sources.length > 0 && (
            <div className="max-w-[80%]">
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
      ))}
      <div ref={bottomRef} />
    </div>
  );
}
