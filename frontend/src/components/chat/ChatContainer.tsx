"use client";

import { useEffect, useRef } from "react";
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

export function ChatContainer() {
  const {
    messages,
    currentStep,
    isLoading,
    latestResponse,
    startSession,
    sendMessage,
    sendAction,
    resetChat,
  } = useChat();

  // D) diagnosing 中の ChatInput に対して「自由入力」ボタンからフォーカスできるよう ref を保持
  const chatInputRef = useRef<ChatInputHandle>(null);

  useEffect(() => {
    startSession();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const prompt = latestResponse?.prompt;
  const isDone = currentStep === "done" || currentStep === "expired";
  const isDiagnosing = currentStep === "diagnosing";

  // ── ハンドラー ────────────────────────────────────────────────────────

  const handleVehicleSelect = (vehicleId: string, displayName: string) => {
    sendAction("select_vehicle", vehicleId, displayName);
  };

  const handleConfirm = (value: string, label: string) => {
    sendAction("confirm", value, label);
  };

  /** provide_answer 後の yes / no / book 専用（sendAction） */
  const handleResolved = (value: string, label: string) => {
    sendAction("resolved", value, label);
  };

  /**
   * D) diagnosing 中の全 single_choice に使う統合ハンドラー。
   * - yes / no / book → sendAction("resolved", ...) （provide_answer 後の選択肢）
   * - それ以外 → sendMessage(label) （質問への回答）
   */
  const handleDiagnosingChoice = (value: string, label: string) => {
    if (value === "yes" || value === "no" || value === "book") {
      sendAction("resolved", value, label);
    } else {
      sendMessage(label);
    }
  };

  /** D) diagnosis_candidates ボタン押下 → メッセージ送信 */
  const handleCandidateSelect = (_value: string, label: string) => {
    sendMessage(label);
  };

  /** D) 「✏️ 自由入力」押下 → ChatInput にフォーカスするだけ（送信しない） */
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
      <MessageList messages={messages} />

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

        {/* single_choice:
            - diagnosing 中 → handleDiagnosingChoice（yes/no/book は resolved、それ以外は sendMessage）
            - それ以外 → handleResolved（sendAction） */}
        {!isLoading && prompt?.type === "single_choice" && prompt.choices && !isDone && (
          <ChoiceButtons
            choices={prompt.choices}
            onSelect={isDiagnosing ? handleDiagnosingChoice : handleResolved}
            onFreeInput={isDiagnosing ? handleFreeInput : undefined}
            disabled={isLoading}
          />
        )}

        {/* diagnosis_candidates: 2列グリッド、候補選択は sendMessage */}
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

        {/* D) free_text は text のみ、diagnosing は prompt タイプ問わず常時入力可 */}
        {!isLoading && !isDone && currentStep === "free_text" && prompt?.type === "text" && (
          <ChatInput onSend={sendMessage} disabled={isLoading} />
        )}
        {!isLoading && !isDone && isDiagnosing && (
          <ChatInput ref={chatInputRef} onSend={sendMessage} disabled={isLoading} />
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
