"use client";

import { useState, useCallback, useRef } from "react";
import { sendChat } from "@/lib/api";
import type { ChatMessage, ChatResponse, UrgencyInfo } from "@/lib/types";

export function useChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [currentStep, setCurrentStep] = useState<string>("vehicle_id");
  const [isLoading, setIsLoading] = useState(false);
  const [latestResponse, setLatestResponse] = useState<ChatResponse | null>(null);
  const idCounter = useRef(0);

  const genId = () => {
    idCounter.current += 1;
    return `msg-${idCounter.current}`;
  };

  const addAssistantMessage = useCallback((response: ChatResponse) => {
    const msg: ChatMessage = {
      id: genId(),
      role: "assistant",
      content: response.prompt.message,
      prompt: response.prompt,
      urgency: response.urgency,
      rag_sources: response.rag_sources,
      timestamp: new Date(),
    };
    setMessages((prev) => [...prev, msg]);
  }, []);

  const startSession = useCallback(async () => {
    setIsLoading(true);
    try {
      const response = await sendChat({
        session_id: null,
        message: null,
        action: null,
        action_value: null,
      });
      setSessionId(response.session_id);
      setCurrentStep(response.current_step);
      setLatestResponse(response);
      addAssistantMessage(response);
    } finally {
      setIsLoading(false);
    }
  }, [addAssistantMessage]);

  const sendMessage = useCallback(
    async (message: string) => {
      const userMsg: ChatMessage = {
        id: genId(),
        role: "user",
        content: message,
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, userMsg]);
      setIsLoading(true);
      try {
        const response = await sendChat({
          session_id: sessionId,
          message,
          action: null,
          action_value: null,
        });
        setSessionId(response.session_id);
        setCurrentStep(response.current_step);
        setLatestResponse(response);
        addAssistantMessage(response);
      } finally {
        setIsLoading(false);
      }
    },
    [sessionId, addAssistantMessage]
  );

  const sendAction = useCallback(
    async (action: string, actionValue: string, displayText?: string) => {
      if (displayText) {
        const userMsg: ChatMessage = {
          id: genId(),
          role: "user",
          content: displayText,
          timestamp: new Date(),
        };
        setMessages((prev) => [...prev, userMsg]);
      }
      setIsLoading(true);
      try {
        const response = await sendChat({
          session_id: sessionId,
          message: null,
          action,
          action_value: actionValue,
        });
        setSessionId(response.session_id);
        setCurrentStep(response.current_step);
        setLatestResponse(response);
        addAssistantMessage(response);
      } finally {
        setIsLoading(false);
      }
    },
    [sessionId, addAssistantMessage]
  );

  const resetChat = useCallback(() => {
    setMessages([]);
    setSessionId(null);
    setCurrentStep("vehicle_id");
    setLatestResponse(null);
    idCounter.current = 0;
  }, []);

  return {
    messages,
    sessionId,
    currentStep,
    isLoading,
    latestResponse,
    startSession,
    sendMessage,
    sendAction,
    resetChat,
  };
}
