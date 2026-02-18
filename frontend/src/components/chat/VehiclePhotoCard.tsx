import { Card } from "@/components/ui/Card";
import { ChoiceButtons } from "./ChoiceButtons";

interface VehiclePhotoCardProps {
  photoUrl: string | null | undefined;
  message: string;
  choices: { value: string; label: string }[];
  onSelect: (value: string, label: string) => void;
  disabled?: boolean;
}

export function VehiclePhotoCard({
  photoUrl,
  message,
  choices,
  onSelect,
  disabled,
}: VehiclePhotoCardProps) {
  return (
    <Card className="overflow-hidden animate-fade-in">
      {photoUrl && (
        <div className="bg-gray-100 h-48 flex items-center justify-center">
          <img
            src={photoUrl}
            alt="車両写真"
            className="max-h-full max-w-full object-contain"
            onError={(e) => {
              (e.target as HTMLImageElement).style.display = "none";
              (e.target as HTMLImageElement).parentElement!.innerHTML =
                '<div class="text-gray-400 text-sm">写真が見つかりません</div>';
            }}
          />
        </div>
      )}
      <div className="p-4 space-y-3">
        <p className="text-sm text-gray-800">{message}</p>
        <ChoiceButtons choices={choices} onSelect={onSelect} disabled={disabled} />
      </div>
    </Card>
  );
}
