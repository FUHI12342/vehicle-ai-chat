"use client";

import { Header } from "@/components/layout/Header";
import { ChatContainer } from "@/components/chat/ChatContainer";

export default function Home() {
  return (
    <div className="flex flex-col h-screen">
      <Header />
      <main className="flex-1 overflow-hidden">
        <ChatContainer />
      </main>
    </div>
  );
}
