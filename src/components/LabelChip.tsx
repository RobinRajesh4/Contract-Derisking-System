import { X } from "lucide-react";
import { Badge } from "@/components/ui/badge";

interface LabelChipProps {
  name: string;
  color: string;
  onRemove?: () => void;
  onClick?: () => void;
  showRemove?: boolean;
}

export function LabelChip({ name, color, onRemove, onClick, showRemove = false }: LabelChipProps) {
  return (
    <Badge
      className="cursor-pointer gap-1 transition-all hover:opacity-80"
      style={{ 
        backgroundColor: color,
        color: getContrastColor(color),
      }}
      onClick={onClick}
    >
      {name}
      {showRemove && onRemove && (
        <X
          className="h-3 w-3 ml-1 hover:scale-110"
          onClick={(e) => {
            e.stopPropagation();
            onRemove();
          }}
        />
      )}
    </Badge>
  );
}

// Helper to ensure readable text on colored backgrounds
function getContrastColor(hexColor: string): string {
  const r = parseInt(hexColor.slice(1, 3), 16);
  const g = parseInt(hexColor.slice(3, 5), 16);
  const b = parseInt(hexColor.slice(5, 7), 16);
  const luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
  return luminance > 0.5 ? '#000000' : '#ffffff';
}
