import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Plus } from "lucide-react";

export interface PolicyLabel {
  id: string;
  name: string;
  parentLabelId: string | null;
  color: string;
  policyIds: string[];
}

interface LabelManagerProps {
  labels: PolicyLabel[];
  onCreateLabel: (label: Omit<PolicyLabel, "id" | "policyIds">) => void;
}

const DEFAULT_COLORS = [
  "#ef4444", // red
  "#f97316", // orange
  "#eab308", // yellow
  "#22c55e", // green
  "#3b82f6", // blue
  "#a855f7", // purple
  "#6b7280", // gray
  "#ec4899", // pink
];

export function LabelManager({ labels, onCreateLabel }: LabelManagerProps) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [isNested, setIsNested] = useState(false);
  const [parentId, setParentId] = useState<string | null>(null);
  const [selectedColor, setSelectedColor] = useState(DEFAULT_COLORS[0]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onCreateLabel({
      name,
      parentLabelId: isNested ? parentId : null,
      color: selectedColor,
    });
    setOpen(false);
    resetForm();
  };

  const resetForm = () => {
    setName("");
    setIsNested(false);
    setParentId(null);
    setSelectedColor(DEFAULT_COLORS[0]);
  };

  const parentLabels = labels.filter(l => l.parentLabelId === null);

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm" onClick={resetForm}>
          <Plus className="mr-2 h-4 w-4" />
          Create Label
        </Button>
      </DialogTrigger>
      <DialogContent>
        <form onSubmit={handleSubmit}>
          <DialogHeader>
            <DialogTitle>Create New Label</DialogTitle>
            <DialogDescription>
              Organize your policies with labels. You can nest labels to create a hierarchy.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label htmlFor="labelName">Label Name</Label>
              <Input
                id="labelName"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g., Payment Terms"
                required
              />
            </div>

            <div className="space-y-2">
              <Label>Label Color</Label>
              <div className="flex gap-2 flex-wrap">
                {DEFAULT_COLORS.map((color) => (
                  <button
                    key={color}
                    type="button"
                    className="h-8 w-8 rounded-full border-2 transition-all hover:scale-110"
                    style={{
                      backgroundColor: color,
                      borderColor: selectedColor === color ? "#000" : "transparent",
                    }}
                    onClick={() => setSelectedColor(color)}
                  />
                ))}
              </div>
            </div>

            <div className="flex items-center space-x-2">
              <Checkbox
                id="nestLabel"
                checked={isNested}
                onCheckedChange={(checked) => setIsNested(checked as boolean)}
              />
              <Label htmlFor="nestLabel" className="cursor-pointer">
                Nest label under
              </Label>
            </div>

            {isNested && parentLabels.length > 0 && (
              <div className="space-y-2">
                <Label htmlFor="parentLabel">Parent Label</Label>
                <Select value={parentId || ""} onValueChange={setParentId}>
                  <SelectTrigger>
                    <SelectValue placeholder="Select parent label" />
                  </SelectTrigger>
                  <SelectContent>
                    {parentLabels.map((label) => (
                      <SelectItem key={label.id} value={label.id}>
                        <div className="flex items-center gap-2">
                          <div
                            className="h-3 w-3 rounded-full"
                            style={{ backgroundColor: label.color }}
                          />
                          {label.name}
                        </div>
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button type="submit">Create</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
