// AUTO-GENERATED — do not edit manually
// Run: npm run generate:architecture

export const architectureDiagram = `
graph TB
  %% ─── Frontend Layer ───
  subgraph Frontend["Frontend （Next.js 15 / React 19）"]
    UI["UI Components<br/>ChatContainer / ChatInput / ChoiceButtons / MessageBubble<br/>MessageList / ReservationForm / TypingIndicator / UrgencyAlert<br/>VehiclePhotoCard / VehicleSearch"]
    Hooks["Hooks<br/>useChat / useSession"]
    APIClient["API Client<br/>lib/api.ts"]
    UI --> Hooks --> APIClient
  end

  %% ─── Next.js Proxy ───
  subgraph Proxy["Next.js API Proxy"]
    ProxyRoute["/api/* → FastAPI"]
  end

  APIClient --> ProxyRoute

  %% ─── Backend API Layer ───
  subgraph BackendAPI["Backend API （FastAPI）"]
    AdminRouter["/admin/ingest"]
    ChatRouter["/chat"]
    HealthRouter["/health"]
    ProvidersRouter["/providers"]
    VehiclesRouter["/vehicles/search"]
  end

  ProxyRoute --> BackendAPI

  %% ─── Service Layer ───
  subgraph Services["Services"]
    ChatService["ChatService"]
    RAGService["RAGService"]
    SessionStore["SessionStore<br/>（in-memory + TTL）"]
    UrgencyAssessor["UrgencyAssessor<br/>keyword + LLM 二段階"]
    VehicleService["VehicleService"]
  end

  ChatRouter --> ChatService
  ChatService --> SessionStore
  VehiclesRouter --> VehicleService
  ChatService --> RAGService
  ChatService --> UrgencyAssessor

  %% ─── Chat Flow State Machine ───
  subgraph ChatFlow["Chat Flow State Machine"]
    direction LR
    S1["vehicle_id"]
    S2["photo_confirm"]
    S3["free_text"]
    S4["spec_check"]
    S5["diagnosing"]
    S6["urgency_check"]
    S7["reservation"]
    S8["booking_info"]
    S9["booking_confirm"]
    S10["done"]
    S1 --> S2
    S2 --> S3
    S3 --> S4
    S3 --> S5
    S4 --> S5
    S5 --> S6
    S5 --> S7
    S6 --> S7
    S7 --> S8
    S8 --> S9
    S9 --> S10
    S3 -.->|CRITICAL| S7
    S5 -.->|resolved| S10
  end

  ChatService --> ChatFlow

  %% ─── LLM Layer ───
  subgraph LLM["LLM Layer"]
    Registry["ProviderRegistry"]
    Bedrock["AWS Bedrock (Claude)"]
    Gemini["Google Gemini"]
    OpenAI["OpenAI GPT-4"]
    Watson["IBM Watson"]
    Registry --> Bedrock
    Registry --> Gemini
    Registry --> OpenAI
    Registry --> Watson
  end

  ChatFlow --> Registry
  UrgencyAssessor --> Registry
  ProvidersRouter --> Registry

  %% ─── RAG Pipeline ───
  subgraph RAG["RAG Pipeline"]
    PDFLoader["PDFLoader<br/>PyPDF2"]
    Chunker["AutomotiveChunker<br/>content-type 分類"]
    Embedder["Embedder<br/>OpenAI / local"]
    ChromaDB["VehicleManualStore<br/>vehicle_manuals"]
    PDFLoader --> Chunker --> Embedder --> ChromaDB
  end

  RAGService --> ChromaDB
  AdminRouter --> PDFLoader

  %% ─── Data Layer ───
  subgraph Data["Data Layer"]
    VehiclesJSON["vehicles.json"]
    PDFs["PDF マニュアル"]
    ChromaData["chroma_data/"]
  end

  VehicleService --> VehiclesJSON
  PDFLoader --> PDFs
  ChromaDB --> ChromaData

  %% ─── Styles ───
  classDef frontend fill:#dbeafe,stroke:#3b82f6,color:#1e3a5f
  classDef proxy fill:#e0e7ff,stroke:#6366f1,color:#312e81
  classDef api fill:#fef3c7,stroke:#f59e0b,color:#78350f
  classDef service fill:#d1fae5,stroke:#10b981,color:#064e3b
  classDef flow fill:#fce7f3,stroke:#ec4899,color:#831843
  classDef llm fill:#ede9fe,stroke:#8b5cf6,color:#4c1d95
  classDef rag fill:#ffedd5,stroke:#f97316,color:#7c2d12
  classDef data fill:#f1f5f9,stroke:#64748b,color:#1e293b

  class Frontend frontend
  class Proxy proxy
  class BackendAPI api
  class Services service
  class ChatFlow flow
  class LLM llm
  class RAG rag
  class Data data
`;
