import { useEffect, useRef, useState } from "react";
import {
  hasSavedPolicyLibrary,
  loadPolicyLibrary,
  resetPolicyLibrary,
  savePolicyLibrary,
  unusedPolicies,
} from "@/policy/policyLibrary";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { Plus, Trash2, Edit, Tags } from "lucide-react";
import { LabelManager, PolicyLabel } from "@/components/LabelManager";
import { LabelChip } from "@/components/LabelChip";
import { LabelTree } from "@/components/LabelTree";
import { Checkbox } from "@/components/ui/checkbox";
import { ScrollArea } from "@/components/ui/scroll-area";
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

interface Policy {
  id: string;
  name: string;
  description: string;
  riskLevel: "high" | "medium" | "low";
  labelIds: string[];
}

export default function Policies() {
  const [policies, setPolicies] = useState<Policy[]>(() => loadPolicyLibrary().policies);

  const [labels, setLabels] = useState<PolicyLabel[]>(() => loadPolicyLibrary().labels);

  // Save edits (not the first render), so they survive navigation and
  // are used by the next analysis (see policy/policyLibrary.ts).
  const firstRender = useRef(true);
  const [customized, setCustomized] = useState(() => hasSavedPolicyLibrary());
  useEffect(() => {
    if (firstRender.current) {
      firstRender.current = false;
      return;
    }
    if (savePolicyLibrary({ policies, labels })) setCustomized(true);
  }, [policies, labels]);

  const resetToDefaults = () => {
    const defaults = resetPolicyLibrary();
    firstRender.current = true; // the reset itself isn't an edit
    setPolicies(defaults.policies);
    setLabels(defaults.labels);
    setCustomized(false);
  };

  const notUsed = unusedPolicies({ policies, labels });

  const [selectedLabelId, setSelectedLabelId] = useState<string | null>(null);

  const [open, setOpen] = useState(false);
  const [editingPolicy, setEditingPolicy] = useState<Policy | null>(null);
  const [labelSearchQuery, setLabelSearchQuery] = useState("");
  const [formData, setFormData] = useState({
    name: "",
    description: "",
    riskLevel: "medium" as "high" | "medium" | "low",
    labelIds: [] as string[],
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (editingPolicy) {
      setPolicies(policies.map(p => p.id === editingPolicy.id ? { ...editingPolicy, ...formData } : p));
    } else {
      setPolicies([...policies, { id: Date.now().toString(), ...formData }]);
    }
    setOpen(false);
    resetForm();
  };

  const resetForm = () => {
    setFormData({ name: "", description: "", riskLevel: "medium", labelIds: [] });
    setEditingPolicy(null);
    setLabelSearchQuery("");
  };

  const handleEdit = (policy: Policy) => {
    setEditingPolicy(policy);
    setFormData({
      name: policy.name,
      description: policy.description,
      riskLevel: policy.riskLevel,
      labelIds: policy.labelIds,
    });
    setOpen(true);
  };

  const handleDelete = (id: string) => {
    setPolicies(policies.filter(p => p.id !== id));
    // Remove policy from all labels
    setLabels(labels.map(label => ({
      ...label,
      policyIds: label.policyIds.filter(pid => pid !== id)
    })));
  };

  const handleCreateLabel = (labelData: Omit<PolicyLabel, "id" | "policyIds">) => {
    const newLabel: PolicyLabel = {
      ...labelData,
      id: Date.now().toString(),
      policyIds: [],
    };
    setLabels([...labels, newLabel]);
  };

  const handleDeleteLabel = (labelId: string) => {
    // Remove child labels first
    const childLabelIds = labels.filter(l => l.parentLabelId === labelId).map(l => l.id);
    setLabels(labels.filter(l => l.id !== labelId && !childLabelIds.includes(l.id)));
    
    // Remove label from all policies
    setPolicies(policies.map(policy => ({
      ...policy,
      labelIds: policy.labelIds.filter(lid => lid !== labelId && !childLabelIds.includes(lid))
    })));
  };

  const togglePolicyLabel = (labelId: string) => {
    setFormData(prev => ({
      ...prev,
      labelIds: prev.labelIds.includes(labelId)
        ? prev.labelIds.filter(id => id !== labelId)
        : [...prev.labelIds, labelId]
    }));
  };

  const removePolicyLabel = (policyId: string, labelId: string) => {
    setPolicies(policies.map(p => 
      p.id === policyId 
        ? { ...p, labelIds: p.labelIds.filter(id => id !== labelId) }
        : p
    ));
    setLabels(labels.map(l =>
      l.id === labelId
        ? { ...l, policyIds: l.policyIds.filter(id => id !== policyId) }
        : l
    ));
  };

  const filteredPolicies = selectedLabelId
    ? policies.filter(p => p.labelIds.includes(selectedLabelId))
    : policies;

  const filteredLabelsForDialog = labels.filter(label =>
    label.name.toLowerCase().includes(labelSearchQuery.toLowerCase())
  );

  return (
    <div className="flex gap-6">
      {/* Label Sidebar */}
      <Card className="w-80 flex-shrink-0 h-fit sticky top-6">
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle className="text-lg flex items-center gap-2">
              <Tags className="h-5 w-5" />
              Labels
            </CardTitle>
          </div>
          <div className="pt-2">
            <LabelManager labels={labels} onCreateLabel={handleCreateLabel} />
          </div>
        </CardHeader>
        <CardContent className="p-0">
          <ScrollArea className="h-[calc(100vh-280px)]">
            <div className="p-6">
              <LabelTree
                labels={labels}
                selectedLabelId={selectedLabelId}
                onSelectLabel={setSelectedLabelId}
                onDeleteLabel={handleDeleteLabel}
              />
            </div>
          </ScrollArea>
        </CardContent>
      </Card>

      {/* Main Content */}
      <div className="flex-1 space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold tracking-tight">Policy Library</h1>
            <p className="text-muted-foreground">
              {selectedLabelId 
                ? `Showing policies with label: ${labels.find(l => l.id === selectedLabelId)?.name}`
                : "Manage compliance policies used for contract analysis"
              }
            </p>
            <p className="mt-1 text-xs text-muted-foreground">
              {customized
                ? "Your edits are saved in this browser and used for every new analysis."
                : "Using the built-in policies. Edits are saved in this browser and used for new analyses."}
            </p>
            {notUsed.length > 0 && (
              <p className="mt-1 text-xs text-amber-600">
                {notUsed.length} {notUsed.length === 1 ? "policy isn't" : "policies aren't"} used in analysis,
                because {notUsed.length === 1 ? "its" : "their"} category isn't one of the analysis domains:{" "}
                {notUsed.slice(0, 4).map((p) => p.name).join(", ")}
                {notUsed.length > 4 ? ", …" : ""}
              </p>
            )}
          </div>
          <div className="flex items-center gap-2">
          {customized && (
            <Button variant="outline" onClick={resetToDefaults} title="Discard your edits and use the built-in policies">
              Reset to defaults
            </Button>
          )}
          <Dialog open={open} onOpenChange={setOpen}>
            <DialogTrigger asChild>
              <Button onClick={resetForm}>
                <Plus className="mr-2 h-4 w-4" />
                Add Policy
              </Button>
            </DialogTrigger>
            <DialogContent className="max-w-2xl">
              <form onSubmit={handleSubmit}>
                <DialogHeader>
                  <DialogTitle>{editingPolicy ? "Edit" : "Add"} Policy</DialogTitle>
                  <DialogDescription>
                    Define a compliance policy that will be used to analyze contracts
                  </DialogDescription>
                </DialogHeader>
                <div className="space-y-4 py-4">
                  <div className="space-y-2">
                    <Label htmlFor="name">Policy Name</Label>
                    <Input
                      id="name"
                      value={formData.name}
                      onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                      required
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="description">Policy Statement</Label>
                    <Textarea
                      id="description"
                      value={formData.description}
                      onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                      required
                    />
                  </div>
                  <div className="space-y-2">
                    <Label htmlFor="riskLevel">Risk Level</Label>
                    <Select
                      value={formData.riskLevel}
                      onValueChange={(value: "high" | "medium" | "low") =>
                        setFormData({ ...formData, riskLevel: value })
                      }
                    >
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="high">High</SelectItem>
                        <SelectItem value="medium">Medium</SelectItem>
                        <SelectItem value="low">Low</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>

                  <div className="space-y-2">
                    <Label>Assign Labels</Label>
                    <Input
                      placeholder="Search labels..."
                      value={labelSearchQuery}
                      onChange={(e) => setLabelSearchQuery(e.target.value)}
                      className="mb-2"
                    />
                    <div className="border rounded-md p-3 max-h-48 overflow-y-auto space-y-2">
                      {labels.length === 0 ? (
                        <p className="text-sm text-muted-foreground">No labels available. Create labels first.</p>
                      ) : filteredLabelsForDialog.length === 0 ? (
                        <p className="text-sm text-muted-foreground">No labels match your search.</p>
                      ) : (
                        filteredLabelsForDialog.map(label => (
                          <div key={label.id} className="flex items-center space-x-2">
                            <Checkbox
                              id={`label-${label.id}`}
                              checked={formData.labelIds.includes(label.id)}
                              onCheckedChange={() => togglePolicyLabel(label.id)}
                            />
                            <label
                              htmlFor={`label-${label.id}`}
                              className="flex items-center gap-2 cursor-pointer flex-1"
                            >
                              <div
                                className="h-3 w-3 rounded-full"
                                style={{ backgroundColor: label.color }}
                              />
                              <span className="text-sm">{label.name}</span>
                            </label>
                          </div>
                        ))
                      )}
                    </div>
                  </div>
                </div>
                <DialogFooter>
                  <Button type="submit">{editingPolicy ? "Update" : "Create"} Policy</Button>
                </DialogFooter>
              </form>
            </DialogContent>
          </Dialog>
          </div>
        </div>

        <div className="grid gap-4">
          {filteredPolicies.length === 0 ? (
            <Card>
              <CardContent className="py-8 text-center">
                <p className="text-muted-foreground">
                  {selectedLabelId 
                    ? "No policies with this label"
                    : "No policies yet. Create one to get started."
                  }
                </p>
              </CardContent>
            </Card>
          ) : (
            filteredPolicies.map((policy) => (
              <Card key={policy.id}>
                <CardHeader>
                  <div className="flex items-start justify-between">
                    <div className="space-y-2 flex-1">
                      <CardTitle>{policy.name}</CardTitle>
                      <CardDescription>{policy.description}</CardDescription>
                      {policy.labelIds.length > 0 && (
                        <div className="flex flex-wrap gap-2 pt-2">
                          {policy.labelIds.map(labelId => {
                            const label = labels.find(l => l.id === labelId);
                            if (!label) return null;
                            return (
                              <LabelChip
                                key={labelId}
                                name={label.name}
                                color={label.color}
                                showRemove
                                onRemove={() => removePolicyLabel(policy.id, labelId)}
                                onClick={() => setSelectedLabelId(labelId)}
                              />
                            );
                          })}
                        </div>
                      )}
                    </div>
                    <div className="flex gap-2">
                      <Button
                        variant="outline"
                        size="icon"
                        onClick={() => handleEdit(policy)}
                      >
                        <Edit className="h-4 w-4" />
                      </Button>
                      <Button
                        variant="outline"
                        size="icon"
                        onClick={() => handleDelete(policy.id)}
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                  </div>
                </CardHeader>
                <CardContent>
                  <Badge
                    variant={
                      policy.riskLevel === "high"
                        ? "destructive"
                        : policy.riskLevel === "medium"
                        ? "secondary"
                        : "outline"
                    }
                  >
                    {policy.riskLevel.toUpperCase()} RISK LEVEL
                  </Badge>
                </CardContent>
              </Card>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
