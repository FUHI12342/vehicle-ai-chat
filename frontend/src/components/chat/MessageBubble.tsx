import type { ChatMessage } from "@/lib/types";

interface MessageBubbleProps {
  message: ChatMessage;
  onRewind?: (turn: number) => void;
  showRewind?: boolean;
}

export function MessageBubble({ message, onRewind, showRewind }: MessageBubbleProps) {
  const isUser = message.role === "user";

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"} animate-fade-in`}>
      <div className={isUser ? "flex flex-col items-end" : ""}>
        <div
          className={`max-w-[80%] px-4 py-3 rounded-2xl text-sm leading-relaxed whitespace-pre-wrap ${
            isUser
              ? "bg-blue-600 text-white rounded-br-sm"
              : "bg-gray-100 text-gray-800 rounded-bl-sm"
          }`}
        >
          {message.content}
        </div>
        {isUser && showRewind && message.diagnosticTurn != null && onRewind && (
          <button
            type="button"
            className="mt-1 text-xs text-blue-500 hover:text-blue-700 hover:underline"
            onClick={() => onRewind(message.diagnosticTurn!)}
          >
            やり直す
          </button>
        )}
      </div>
    </div>
  );
}
