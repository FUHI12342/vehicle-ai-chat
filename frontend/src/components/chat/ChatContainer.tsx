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
// 2) 原因候補ラベル固定マッピング（frontendのみ）
// ─────────────────────────────────────────────────────────────────────────────

const LABEL_MAP: Record<string, string> = {
  // ブレーキ系
  "ブレーキパッド摩耗（キーキー/金属音）": "パッド摩耗（キーキー/金属音）",
  "ブレーキパッド": "パッド摩耗（キーキー/金属音）",
  "ブレーキローター（擦れ/振動）": "ローター不具合（振動/擦れ）",
  "ブレーキディスク損傷": "ディスク不具合（振動/削れ）",
  "ブレーキ液不足": "ブレーキ液不足（効きが弱い）",
  "ブレーキキャリパー故障": "キャリパー不具合（片効き/引きずり）",
  // タイヤ系
  "タイヤ異常（パンク/偏摩耗）": "タイヤ（パンク/偏摩耗）",
  "ハブベアリング（走行異音）": "ハブベアリング（走行中の音）",
  // エンジン系
  "エンジン内部異常（振動/異音）": "エンジン異常（振動/異音）",
  "エンジンオイル（漏れ/不足）": "オイル漏れまたは不足",
  "スパークプラグ不良（点火）": "点火プラグ不良",
  // 電装系
  "バッテリー劣化（始動不良）": "バッテリー劣化（かかりにくい）",
  "オルタネーター（発電機）故障": "発電機（オルタネーター）不具合",
  // サスペンション/駆動系
  "サスペンション（ゴトゴト音）": "サスペンション（ゴトゴト）",
  "ショックアブソーバー劣化": "ショック劣化（衝撃大きい）",
  "CVT（変速機）不具合": "変速機（CVT）不具合",
  "AT（オートマ）不具合": "オートマ（AT）不具合",
  // シフト/電装系追加
  "シフトロック": "シフトロック（解除が必要）",
  "シフトケーブル": "シフトケーブル（引っかかり/断線）",
  "ブレーキスイッチ": "ブレーキスイッチ（踏んでも反応しない）",
  "バッテリー": "バッテリー（電圧不足/端子）",
  "ヒューズ": "ヒューズ（切れ）",
  // 汎用
  "その他": "その他（説明を入力）",
};

const HINT_MAP: { keyword: string; hint: string }[] = [
  { keyword: "シフトロック",    hint: "まずシフトロック解除を確認（ブレーキを踏みながら解除ボタン等）。" },
  { keyword: "シフトケーブル",  hint: "シフトケーブルの引っかかり・断線は専門家に確認してもらってください。" },
  { keyword: "ブレーキスイッチ", hint: "ブレーキを踏んでも変速できない場合、ブレーキスイッチの点検を。" },
  { keyword: "バッテリー",      hint: "まずバッテリーの電圧と端子の緩みを確認してください。" },
  { keyword: "ヒューズ",        hint: "まず該当ヒューズが切れていないか確認してください。" },
];

function getHint(choices: { value: string; label: string }[]): string | null {
  const allText = choices.map(c => `${c.value} ${c.label}`).join(" ");
  for (const { keyword, hint } of HINT_MAP) {
    if (allText.includes(keyword)) return hint;
  }
  return null;
}

function applyLabelMap(
  choices: { value: string; label: string }[]
): { value: string; label: string }[] {
  return choices.map((c) => ({ ...c, label: LABEL_MAP[c.label] ?? c.label }));
}

// ─────────────────────────────────────────────────────────────────────────────

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
  const isDone = currentStep === "done" || currentStep === "expired";
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
    if (value === "yes" || value === "no" || value === "book") {
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

  // 2) diagnosis_candidates の choices に LABEL_MAP を適用
  const candidateChoices = prompt?.choices ? applyLabelMap(prompt.choices) : undefined;

  // single_choice でも「原因として最も近い」メッセージなら LABEL_MAP を適用
  const singleChoices =
    prompt?.choices &&
    isDiagnosing &&
    prompt.message?.includes("原因として最も近い")
      ? applyLabelMap(prompt.choices)
      : prompt?.choices;

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

        {!isLoading && prompt?.type === "single_choice" && singleChoices && !isDone && (
          <>
            {/* HINT: 原因候補 single_choice */}
            {isDiagnosing && prompt.message?.includes("原因として最も近い") && getHint(singleChoices) && (
              <p className="text-xs text-blue-700 bg-blue-50 rounded-lg px-3 py-2">
                💡 {getHint(singleChoices)}
              </p>
            )}
            {/* 3) RAGページ参照（provide_answer後のみ） */}
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
              choices={singleChoices}
              onSelect={isSpecCheck ? handleSpecCheckChoice : isDiagnosing ? handleDiagnosingChoice : handleResolved}
              onFreeInput={isDiagnosing ? handleFreeInput : undefined}
              disabled={isLoading}
            />
          </>
        )}

        {/* 2) diagnosis_candidates: ラベルマップ適用 + HINT + 2列グリッド */}
        {!isLoading && prompt?.type === "diagnosis_candidates" && candidateChoices && !isDone && (
          <>
            {getHint(candidateChoices) && (
              <p className="text-xs text-blue-700 bg-blue-50 rounded-lg px-3 py-2">
                💡 {getHint(candidateChoices)}
              </p>
            )}
            <ChoiceButtons
              choices={candidateChoices}
              onSelect={handleCandidateSelect}
              onFreeInput={handleFreeInput}
              disabled={isLoading}
              grid
            />
          </>
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
