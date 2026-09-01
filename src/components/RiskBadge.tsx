import { Badge } from "@/components/ui/badge";

interface RiskBadgeProps {
  level: "high" | "medium" | "low";
  score?: number;
}

export function RiskBadge({ level, score }: RiskBadgeProps) {
  const variants = {
    high: "destructive",
    medium: "secondary",
    low: "outline",
  } as const;

  const labels = {
    high: "High Risk",
    medium: "Medium Risk",
    low: "Low Risk",
  };

  return (
    <Badge variant={variants[level]} className="font-medium">
      {labels[level]}
      {score !== undefined && ` (${score})`}
    </Badge>
  );
}
