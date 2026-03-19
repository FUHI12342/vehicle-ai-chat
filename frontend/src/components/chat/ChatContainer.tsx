"use client";

import { useEffect, useRef, useState } from "react";
import { useChat } from "@/hooks/useChat";
import { MessageList } from "./MessageList";
import { ChatInput, type ChatInputHandle } from "./ChatInput";
import { TypingIndicator } from "./TypingIndicator";
import { VehicleSearch } from "./VehicleSearch";
import { VehiclePhotoCard } from "./VehiclePhotoCard";
import { ChoiceButtons } from "./ChoiceButtons";
import { ReservationForm } from "./ReservationForm";
import { Button } from "@/components/ui/Button";
import { ja } from "@/i18n/ja";

// ─────────────────────────────────────────────────────────────────────────────
// 1) 誤入力ヒューリスティック（frontendのみ、diagnosing 専用）
// ─────────────────────────────────────────────────────────────────────────────

/** 短くても有効な同意語（送信を止めない） */
const AGREE_SET = new Set([
  "はい", "いいえ", "ok", "no", "yes", "うん", "ええ", "そう",
  "はい。", "いいえ。", "OK", "No", "Yes",
]);

/** 相槌だけの入力（送信を止める） */
const FILLER_SET = new Set(["ほほ", "へえ", "ふーん", "ふん", "あー", "えー", "おー", "うー", "んー"]);

function isSuspiciousInput(text: string): boolean {
  const t = text.trim();
  if (t.length > 10) return false;                          // 十分長ければOK
  if (AGREE_SET.has(t) || AGREE_SET.has(t.toLowerCase())) return false; // 同意語除外

  if (t.length <= 2) return true;                           // 極短（同意語でない）
  if (!/\p{L}/u.test(t)) return true;                      // 文字（字母）が一切ない → 記号/絵文字のみ
  if (/^(.)\1+$/.test(t)) return true;                     // 同じ文字の繰り返し (ww, ああ, ーー …)
  if (FILLER_SET.has(t)) return true;                      // 相槌辞書

  return false;
}

// ─────────────────────────────────────────────────────────────────────────────

export function ChatContainer() {
  const {
    messages,
    currentStep,
    isLoading,
    error,
    latestResponse,
    startSession,
    sendMessage,
    sendAction,
    rewindToTurn,
    resetChat,
  } = useChat();

  const chatInputRef = useRef<ChatInputHandle>(null);

  /** 誤入力確認UI: null=非表示、string=確認待ちテキスト */
  const [pendingConfirm, setPendingConfirm] = useState<string | null>(null);

  useEffect(() => {
    startSession();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // 画面遷移したら確認UIをリセット
  useEffect(() => {
    setPendingConfirm(null);
  }, [currentStep]);

  const prompt = latestResponse?.prompt;
  const isDone = currentStep === "done";
  const isDiagnosing = currentStep === "diagnosing";
  const isSpecCheck = currentStep === "spec_check";
  const isInputGuardEnabled = isDiagnosing || currentStep === "free_text";

  // ── ハンドラー ────────────────────────────────────────────────────────

  const handleVehicleSelect = (vehicleId: string, displayName: string) => {
    sendAction("select_vehicle", vehicleId, displayName);
  };

  const handleConfirm = (value: string, label: string) => {
    sendAction("confirm", value, label);
  };

  const handleResolved = (value: string, label: string) => {
    sendAction("resolved", value, label);
  };

  const handleSpecCheckChoice = (value: string, label: string) => {
    sendAction("resolved", value, label);
  };

  const handleDiagnosingChoice = (value: string, label: string) => {
    if (value === "yes" || value === "no" || value === "book" || value === "guide_start") {
      sendAction("resolved", value, label);
    } else {
      sendMessage(label);
    }
  };

  const handleCandidateSelect = (_value: string, label: string) => {
    sendMessage(label);
  };

  const handleFreeInput = () => {
    chatInputRef.current?.focus();
  };

  const handleReservationChoice = (value: string, label: string) => {
    sendAction("reservation_choice", value, label);
  };

  const handleBookingSubmit = (data: Record<string, string>) => {
    sendAction("submit_booking", JSON.stringify(data));
  };

  const handleBookingConfirm = (value: string, label: string) => {
    sendAction("booking_confirm", value, label);
  };

  /**
   * 1) diagnosing 中だけ誤入力チェックを挟む送信ラッパー。
   *    それ以外のステップはそのまま sendMessage。
   */
  const handleSendMessage = (text: string) => {
    if (!isInputGuardEnabled) {
      sendMessage(text);
      return;
    }
    if (isSuspiciousInput(text)) {
      setPendingConfirm(text);   // 確認UIを表示
    } else {
      sendMessage(text);
    }
  };

  const stepLabel = ja.steps[currentStep as keyof typeof ja.steps] || currentStep;

  return (
    <div className="flex flex-col h-full max-w-4xl mx-auto">
      {/* Step indicator */}
      <div className="px-4 py-2 border-b border-gray-100">
        <div className="flex items-center gap-2 text-xs text-gray-400">
          <span>ステップ:</span>
          <span className="font-medium text-blue-600">{stepLabel}</span>
        </div>
      </div>

      {/* Messages */}
      <MessageList messages={messages} currentStep={currentStep} onRewind={rewindToTurn} />

      {/* Loading indicator */}
      {isLoading && <TypingIndicator />}

      {/* Interactive area */}
      <div className="border-t border-gray-200 px-4 py-3 space-y-3">
        {!isLoading && prompt?.type === "vehicle_search" && !isDone && (
          <VehicleSearch onSelect={handleVehicleSelect} disabled={isLoading} />
        )}

        {!isLoading &&
          prompt?.type === "photo_confirm" &&
          prompt.choices &&
          !isDone && (
            <VehiclePhotoCard
              photoUrl={prompt.vehicle_photo_url}
              message=""
              choices={prompt.choices}
              onSelect={handleConfirm}
              disabled={isLoading}
            />
          )}

        {!isLoading && prompt?.type === "single_choice" && prompt.choices && !isDone && (
          <>
            {/* RAGページ参照（provide_answer後のみ） */}
            {(() => {
              const srcs = latestResponse?.rag_sources ?? [];
              const isAnswer = prompt.choices?.some(c => ["yes", "no", "book"].includes(c.value));
              if (!isAnswer || srcs.length === 0) return null;
              const pages = [...new Set(srcs.map(s => s.section || `p.${s.page}`))].slice(0, 3);
              return (
                <p className="text-xs text-gray-500">
                  📖 参考（マニュアル）: {pages.join(" / ")}
                </p>
              );
            })()}
            <ChoiceButtons
              choices={prompt.choices}
              onSelect={isSpecCheck ? handleSpecCheckChoice : isDiagnosing ? handleDiagnosingChoice : handleResolved}
              onFreeInput={isDiagnosing ? handleFreeInput : undefined}
              disabled={isLoading}
            />
          </>
        )}

        {/* diagnosis_candidates: 2列グリッド */}
        {!isLoading && prompt?.type === "diagnosis_candidates" && prompt.choices && !isDone && (
          <ChoiceButtons
            choices={prompt.choices}
            onSelect={handleCandidateSelect}
            onFreeInput={handleFreeInput}
            disabled={isLoading}
            grid
          />
        )}

        {!isLoading &&
          prompt?.type === "reservation_choice" &&
          prompt.choices &&
          !isDone && (
            <ChoiceButtons
              choices={prompt.choices}
              onSelect={handleReservationChoice}
              disabled={isLoading}
            />
          )}

        {!isLoading &&
          prompt?.type === "booking_form" &&
          prompt.booking_fields &&
          !isDone && (
            <ReservationForm
              fields={prompt.booking_fields}
              bookingType={prompt.booking_type || "visit"}
              onSubmit={handleBookingSubmit}
              disabled={isLoading}
            />
          )}

        {!isLoading &&
          prompt?.type === "booking_confirm" &&
          prompt.choices &&
          !isDone && (
            <ChoiceButtons
              choices={prompt.choices}
              onSelect={handleBookingConfirm}
              disabled={isLoading}
            />
          )}

        {/* free_text */}
        {!isLoading && !isDone && currentStep === "free_text" && prompt?.type === "text" && (
          <>
            {pendingConfirm !== null && (
              <div className="bg-yellow-50 border border-yellow-200 rounded-xl px-4 py-3 text-sm space-y-2">
                <p className="text-yellow-800">
                  「{pendingConfirm}」は入力ミスかもしれません。どうしますか？
                </p>
                <div className="flex gap-2">
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => {
                      setPendingConfirm(null);
                      chatInputRef.current?.focus();
                    }}
                  >
                    書き直す
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => {
                      const t = pendingConfirm;
                      setPendingConfirm(null);
                      sendMessage(t);
                    }}
                  >
                    このまま送る
                  </Button>
                </div>
              </div>
            )}
            <ChatInput ref={chatInputRef} onSend={handleSendMessage} disabled={isLoading} />
          </>
        )}

        {/* diagnosing: 常時入力 + 1) 誤入力確認UI */}
        {!isLoading && !isDone && isDiagnosing && (
          <>
            {pendingConfirm !== null && (
              <div className="bg-yellow-50 border border-yellow-200 rounded-xl px-4 py-3 text-sm space-y-2">
                <p className="text-yellow-800">
                  「{pendingConfirm}」は入力ミスかもしれません。どうしますか？
                </p>
                <div className="flex gap-2">
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => {
                      setPendingConfirm(null);
                      chatInputRef.current?.focus();
                    }}
                  >
                    書き直す
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => {
                      const t = pendingConfirm;
                      setPendingConfirm(null);
                      sendMessage(t); // チェックをスキップして直接送信
                    }}
                  >
                    このまま送る
                  </Button>
                </div>
              </div>
            )}
            <ChatInput
              ref={chatInputRef}
              onSend={handleSendMessage}
              disabled={isLoading}
            />
          </>
        )}

        {error && (
          <div className="bg-red-50 border border-red-200 rounded-xl px-4 py-3 text-sm space-y-2">
            <p className="text-red-800">{error}</p>
            <Button
              size="sm"
              variant="primary"
              onClick={() => {
                resetChat();
                startSession();
              }}
            >
              {ja.chat.newSession}
            </Button>
          </div>
        )}

        {isDone && (
          <div className="text-center">
            <Button
              variant="primary"
              onClick={() => {
                resetChat();
                startSession();
              }}
            >
              {ja.chat.newSession}
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}
