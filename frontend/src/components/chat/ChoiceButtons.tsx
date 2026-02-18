import { Button } from "@/components/ui/Button";

interface ChoiceButtonsProps {
  choices: { value: string; label: string }[];
  onSelect: (value: string, label: string) => void;
  disabled?: boolean;
}

export function ChoiceButtons({ choices, onSelect, disabled }: ChoiceButtonsProps) {
  return (
    <div className="flex flex-wrap gap-2 animate-fade-in">
      {choices.map((choice) => (
        <Button
          key={choice.value}
          variant="outline"
          size="md"
          onClick={() => onSelect(choice.value, choice.label)}
          disabled={disabled}
        >
          {choice.label}
        </Button>
      ))}
    </div>
  );
}
