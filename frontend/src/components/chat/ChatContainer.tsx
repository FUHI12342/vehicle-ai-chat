"use client";

import { useEffect } from "react";
import { useChat } from "@/hooks/useChat";
import { MessageList } from "./MessageList";
import { ChatInput } from "./ChatInput";
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

  useEffect(() => {
    startSession();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const prompt = latestResponse?.prompt;
  const isDone = currentStep === "done" || currentStep === "expired";

  const handleVehicleSelect = (vehicleId: string, displayName: string) => {
    sendAction("select_vehicle", vehicleId, displayName);
  };

  const handleConfirm = (value: string, label: string) => {
    sendAction("confirm", value, label);
  };

  const handleResolved = (value: string, label: string) => {
    sendAction("resolved", value, label);
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

        {!isLoading &&
          prompt?.type === "single_choice" &&
          prompt.choices &&
          !isDone && (
            <ChoiceButtons
              choices={prompt.choices}
              onSelect={handleResolved}
              disabled={isLoading}
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

        {!isLoading &&
          prompt?.type === "text" &&
          (currentStep === "free_text" || currentStep === "diagnosing") && (
            <ChatInput onSend={sendMessage} disabled={isLoading} />
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
