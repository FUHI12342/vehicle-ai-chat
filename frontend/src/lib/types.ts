export interface ChatRequest {
  session_id: string | null;
  message: string | null;
  action: string | null;
  action_value: string | null;
}

export interface RAGSource {
  content: string;
  page: number;
  section: string;
  score: number;
}

export interface UrgencyInfo {
  level: "low" | "medium" | "high" | "critical";
  requires_visit: boolean;
  reasons: string[];
}

export interface BookingField {
  name: string;
  label: string;
  type: string;
  required: boolean;
}

export interface BookingData {
  name?: string;
  phone?: string;
  address?: string;
  preferred_date?: string;
}

export interface PromptInfo {
  type:
    | "text"
    | "single_choice"
    | "diagnosis_candidates"
    | "vehicle_search"
    | "photo_confirm"
    | "reservation_choice"
    | "booking_form"
    | "booking_confirm";
  message: string;
  choices?: { value: string; label: string }[];
  vehicle_photo_url?: string | null;
  booking_type?: "dispatch" | "visit" | null;
  booking_fields?: BookingField[] | null;
  booking_summary?: BookingData | null;
}

export interface ChatResponse {
  session_id: string;
  current_step: string;
  prompt: PromptInfo;
  urgency?: UrgencyInfo | null;
  rag_sources: RAGSource[];
}

export interface Vehicle {
  id: string;
  make: string;
  model: string;
  year: number;
  trim: string;
  photo_url: string;
  manual_available: boolean;
}

export interface VehicleMatch {
  vehicle: Vehicle;
  score: number;
}

export interface ProviderInfo {
  name: string;
  display_name: string;
  is_configured: boolean;
  is_active: boolean;
}

export interface ProviderListResponse {
  providers: ProviderInfo[];
  active: string;
}

export interface ChatMessage {
  id: string;
  role: "assistant" | "user";
  content: string;
  prompt?: PromptInfo;
  urgency?: UrgencyInfo | null;
  rag_sources?: RAGSource[];
  timestamp: Date;
}
