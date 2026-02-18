"use client";

import { useState } from "react";
import type { BookingField } from "@/lib/types";

interface ReservationFormProps {
  fields: BookingField[];
  bookingType: string;
  onSubmit: (data: Record<string, string>) => void;
  disabled?: boolean;
}

export function ReservationForm({
  fields,
  bookingType,
  onSubmit,
  disabled,
}: ReservationFormProps) {
  const [formData, setFormData] = useState<Record<string, string>>(() => {
    const initial: Record<string, string> = {};
    for (const field of fields) {
      initial[field.name] = "";
    }
    return initial;
  });
  const [errors, setErrors] = useState<Record<string, string>>({});

  const handleChange = (name: string, value: string) => {
    setFormData((prev) => ({ ...prev, [name]: value }));
    if (errors[name]) {
      setErrors((prev) => {
        const next = { ...prev };
        delete next[name];
        return next;
      });
    }
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const newErrors: Record<string, string> = {};
    for (const field of fields) {
      if (field.required && !formData[field.name]?.trim()) {
        newErrors[field.name] = `${field.label}を入力してください`;
      }
    }
    if (Object.keys(newErrors).length > 0) {
      setErrors(newErrors);
      return;
    }
    onSubmit(formData);
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4 animate-fade-in">
      <div className="text-sm font-medium text-gray-700">
        {bookingType === "dispatch" ? "出張手配情報" : "来店予約情報"}
      </div>
      {fields.map((field) => (
        <div key={field.name}>
          <label
            htmlFor={field.name}
            className="block text-sm font-medium text-gray-600 mb-1"
          >
            {field.label}
            {field.required && <span className="text-red-500 ml-1">*</span>}
          </label>
          <input
            id={field.name}
            type={field.type === "tel" ? "tel" : "text"}
            value={formData[field.name] || ""}
            onChange={(e) => handleChange(field.name, e.target.value)}
            disabled={disabled}
            className={`w-full px-3 py-2 border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-400 disabled:opacity-50 ${
              errors[field.name]
                ? "border-red-400 bg-red-50"
                : "border-gray-300 bg-white"
            }`}
            placeholder={field.label}
          />
          {errors[field.name] && (
            <p className="text-xs text-red-500 mt-1">{errors[field.name]}</p>
          )}
        </div>
      ))}
      <button
        type="submit"
        disabled={disabled}
        className="w-full px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 transition-colors disabled:opacity-50"
      >
        送信
      </button>
    </form>
  );
}
