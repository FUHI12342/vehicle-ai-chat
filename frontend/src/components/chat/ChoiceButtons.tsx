import { Button } from "@/components/ui/Button";

const FREE_INPUT_VALUE = "free_input";

interface Choice {
  value: string;
  label: string;
  icon?: string;
}

interface ChoiceButtonsProps {
  choices: Choice[];
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
  const hasIcons = choices.some((c) => c.icon);

  if (hasIcons) {
    const iconChoices = choices.filter((c) => c.icon);
    const textChoices = choices.filter((c) => !c.icon);

    return (
      <div className="space-y-3 animate-fade-in">
        {/* Icon card grid */}
        <div className="grid grid-cols-3 gap-2">
          {iconChoices.map((choice) => (
            <button
              key={choice.value}
              onClick={() => onSelect(choice.value, choice.label)}
              disabled={disabled}
              className="flex flex-col items-center gap-1.5 rounded-lg border border-gray-300 bg-white p-3 text-center transition-colors hover:bg-amber-50 hover:border-amber-400 focus:outline-none focus:ring-2 focus:ring-amber-400 focus:ring-offset-1 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <img
                src={choice.icon}
                alt={choice.label}
                className="h-10 w-10"
                onError={(e) => {
                  (e.target as HTMLImageElement).style.display = "none";
                }}
              />
              <span className="text-xs font-medium text-gray-700 leading-tight">
                {choice.label}
              </span>
            </button>
          ))}
        </div>
        {/* Text-only choices (e.g. わからない, 自由入力) */}
        {textChoices.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {textChoices.map((choice) => (
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
                className="whitespace-normal h-auto py-2 text-left leading-snug"
              >
                {choice.label}
              </Button>
            ))}
          </div>
        )}
      </div>
    );
  }

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
