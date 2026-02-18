"use client";

import { useState, useCallback } from "react";

export function useSession() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [currentStep, setCurrentStep] = useState<string>("vehicle_id");

  const reset = useCallback(() => {
    setSessionId(null);
    setCurrentStep("vehicle_id");
  }, []);

  return { sessionId, setSessionId, currentStep, setCurrentStep, reset };
}
