import { Button } from "@/components/ui/Button";

const FREE_INPUT_VALUE = "free_input";

interface ChoiceButtonsProps {
  choices: { value: string; label: string }[];
  onSelect: (value: string, label: string) => void;
  /** 「✏️ 自由入力」ボタン押下時に呼ばれる（sendMessage せず入力欄にフォーカス） */
  onFreeInput?: () => void;
  disabled?: boolean;
  /** 2列グリッド（diagnosis_candidates 用） */
  grid?: boolean;
}

export function ChoiceButtons({
  choices,
  onSelect,
  onFreeInput,
  disabled,
  grid,
}: ChoiceButtonsProps) {
  return (
    <div
      className={
        grid
          ? "grid grid-cols-2 gap-2 animate-fade-in"
          : "flex flex-wrap gap-2 animate-fade-in"
      }
    >
      {choices.map((choice) => (
        <Button
          key={choice.value}
          variant="outline"
          size="md"
          onClick={() => {
            if (choice.value === FREE_INPUT_VALUE) {
              onFreeInput?.();
            } else {
              onSelect(choice.value, choice.label);
            }
          }}
          disabled={disabled}
          className={
            grid
              ? "w-full text-sm text-left whitespace-normal h-auto py-2 leading-snug"
              : "whitespace-normal h-auto py-2 text-left leading-snug"
          }
        >
          {choice.label}
        </Button>
      ))}
    </div>
  );
}
