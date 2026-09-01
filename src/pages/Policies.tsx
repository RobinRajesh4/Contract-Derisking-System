import { useState } from "react";
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
  const [policies, setPolicies] = useState<Policy[]>([
    // Financial policies
    {
      id: "1",
      name: "Standard Payment Terms Policy",
      description: "All contracts must adhere to 30-day net payment terms unless exceptional approval is obtained",
      riskLevel: "medium",
      labelIds: ["1", "1.1"],
    },
    {
      id: "2",
      name: "Early Payment Discount Limits",
      description: "Maximum discount for early payment should not exceed 2% for 10-day terms",
      riskLevel: "low",
      labelIds: ["1", "1.2"],
    },
    {
      id: "3",
      name: "Tax Compliance Requirements",
      description: "All contracts must include appropriate tax clauses compliant with local jurisdictions",
      riskLevel: "high",
      labelIds: ["1", "1.3"],
    },
    {
      id: "4",
      name: "Invoice Documentation Standards",
      description: "Invoices must include all required documentation within 5 business days",
      riskLevel: "medium",
      labelIds: ["1", "1.4"],
    },
    {
      id: "5",
      name: "Foreign Exchange Risk Management",
      description: "Contracts exceeding $100K must specify currency and exchange rate mechanisms",
      riskLevel: "medium",
      labelIds: ["1", "1.5"],
    },
    
    // Legal policies
    {
      id: "6",
      name: "Governing Law Preference",
      description: "Contracts should specify governing law of company's primary jurisdiction",
      riskLevel: "high",
      labelIds: ["2", "2.1"],
    },
    {
      id: "7",
      name: "Liability Cap Requirements",
      description: "Liability must be capped at contract value or annual fees, whichever is lower",
      riskLevel: "high",
      labelIds: ["2", "2.2"],
    },
    {
      id: "8",
      name: "Mutual Indemnification",
      description: "Indemnification clauses must be mutual and reasonable in scope",
      riskLevel: "high",
      labelIds: ["2", "2.2"],
    },
    {
      id: "9",
      name: "Confidentiality Period",
      description: "Confidentiality obligations must extend 3-5 years post-termination",
      riskLevel: "medium",
      labelIds: ["2", "2.3"],
    },
    {
      id: "10",
      name: "Force Majeure Definitions",
      description: "Force majeure clauses must include pandemic, natural disasters, and war",
      riskLevel: "medium",
      labelIds: ["2", "2.4"],
    },
    {
      id: "11",
      name: "Termination Notice Period",
      description: "Require minimum 60-day notice for termination without cause",
      riskLevel: "medium",
      labelIds: ["2", "2.5"],
    },
    {
      id: "12",
      name: "Arbitration Clause Standard",
      description: "Disputes should be resolved through binding arbitration in neutral jurisdiction",
      riskLevel: "medium",
      labelIds: ["2", "2.6"],
    },
    
    // Compliance policies
    {
      id: "13",
      name: "GDPR Data Processing Agreement",
      description: "All contracts processing EU data must include GDPR-compliant DPA",
      riskLevel: "high",
      labelIds: ["3", "3.1"],
    },
    {
      id: "14",
      name: "PCI-DSS Compliance for Payment Data",
      description: "Payment processing must meet PCI-DSS Level 1 standards",
      riskLevel: "high",
      labelIds: ["3", "3.1"],
    },
    {
      id: "15",
      name: "AML Transaction Monitoring",
      description: "Implement real-time monitoring for transactions exceeding $10K",
      riskLevel: "high",
      labelIds: ["3", "3.2"],
    },
    {
      id: "16",
      name: "KYC Customer Verification",
      description: "Complete identity verification required for all new business relationships",
      riskLevel: "high",
      labelIds: ["3", "3.3"],
    },
    {
      id: "17",
      name: "Sanctions Screening Requirements",
      description: "Screen all parties against OFAC and international sanctions lists",
      riskLevel: "high",
      labelIds: ["3", "3.4"],
    },
    {
      id: "18",
      name: "Code of Conduct Compliance",
      description: "All vendors must acknowledge and comply with company code of conduct",
      riskLevel: "medium",
      labelIds: ["3", "3.5"],
    },
    
    // Operational policies
    {
      id: "19",
      name: "Uptime SLA Requirements",
      description: "Critical services must guarantee 99.9% uptime with penalties for breaches",
      riskLevel: "high",
      labelIds: ["4", "4.1"],
    },
    {
      id: "20",
      name: "Response Time Standards",
      description: "Support response times: Critical-1hr, High-4hr, Medium-24hr",
      riskLevel: "medium",
      labelIds: ["4", "4.1"],
    },
    {
      id: "21",
      name: "Performance Measurement KPIs",
      description: "Establish clear KPIs and quarterly performance reviews",
      riskLevel: "medium",
      labelIds: ["4", "4.2"],
    },
    {
      id: "22",
      name: "Delivery Timeline Requirements",
      description: "Deliverables must have defined acceptance criteria and timelines",
      riskLevel: "medium",
      labelIds: ["4", "4.3"],
    },
    {
      id: "23",
      name: "Preventive Maintenance Schedule",
      description: "Critical systems require quarterly preventive maintenance windows",
      riskLevel: "low",
      labelIds: ["4", "4.4"],
    },
    
    // Security policies
    {
      id: "24",
      name: "Data Encryption Standards",
      description: "All data must be encrypted using AES-256 at rest and TLS 1.3 in transit",
      riskLevel: "high",
      labelIds: ["5", "5.1"],
    },
    {
      id: "25",
      name: "Multi-Factor Authentication",
      description: "MFA required for all administrative and privileged access",
      riskLevel: "high",
      labelIds: ["5", "5.2"],
    },
    {
      id: "26",
      name: "Security Incident Notification",
      description: "Security breaches must be reported within 24 hours of discovery",
      riskLevel: "high",
      labelIds: ["5", "5.3"],
    },
    {
      id: "27",
      name: "Third-Party Security Assessment",
      description: "Vendors must provide SOC 2 Type II or ISO 27001 certification",
      riskLevel: "high",
      labelIds: ["5", "5.4"],
    },
    
    // Risk & Audit policies
    {
      id: "28",
      name: "Minimum Insurance Coverage",
      description: "Vendors must maintain $5M general liability and $2M cyber insurance",
      riskLevel: "high",
      labelIds: ["6", "6.1"],
    },
    {
      id: "29",
      name: "Risk Assessment Frequency",
      description: "Conduct comprehensive risk assessments annually or upon major changes",
      riskLevel: "medium",
      labelIds: ["6", "6.2"],
    },
    {
      id: "30",
      name: "Audit Access Rights",
      description: "Company reserves right to audit vendor compliance with 30-day notice",
      riskLevel: "medium",
      labelIds: ["6", "6.3"],
    },
    {
      id: "31",
      name: "Monthly Compliance Reporting",
      description: "Vendors must provide monthly compliance and performance reports",
      riskLevel: "low",
      labelIds: ["6", "6.4"],
    },
    
    // Intellectual Property policies
    {
      id: "32",
      name: "IP Ownership Clarity",
      description: "All custom work product and IP must be explicitly assigned to company",
      riskLevel: "high",
      labelIds: ["7", "7.1"],
    },
    {
      id: "33",
      name: "License Grant Restrictions",
      description: "Third-party licenses must be perpetual, non-exclusive, and transferable",
      riskLevel: "medium",
      labelIds: ["7", "7.2"],
    },
    {
      id: "34",
      name: "Patent Indemnification",
      description: "Vendors must indemnify against patent infringement claims",
      riskLevel: "high",
      labelIds: ["7", "7.3"],
    },
    
    // Environmental & Sustainability policies
    {
      id: "35",
      name: "Waste Reduction Targets",
      description: "Vendors must demonstrate commitment to reduce waste by 20% annually",
      riskLevel: "low",
      labelIds: ["8", "8.1"],
    },
    {
      id: "36",
      name: "Sustainable Sourcing Requirements",
      description: "Priority given to vendors with certified sustainable supply chains",
      riskLevel: "low",
      labelIds: ["8", "8.2"],
    },
    {
      id: "37",
      name: "ESG Reporting Standards",
      description: "Annual ESG metrics reporting required for contracts over $500K",
      riskLevel: "medium",
      labelIds: ["8", "8.3"],
    },
  ]);

  const [labels, setLabels] = useState<PolicyLabel[]>([
    // Financial
    { id: "1", name: "Financial", parentLabelId: null, color: "#22c55e", policyIds: ["1", "2", "3", "4", "5"] },
    { id: "1.1", name: "Payment Terms", parentLabelId: "1", color: "#16a34a", policyIds: ["1"] },
    { id: "1.2", name: "Pricing & Discounts", parentLabelId: "1", color: "#16a34a", policyIds: ["2"] },
    { id: "1.3", name: "Taxation", parentLabelId: "1", color: "#16a34a", policyIds: ["3"] },
    { id: "1.4", name: "Invoicing", parentLabelId: "1", color: "#16a34a", policyIds: ["4"] },
    { id: "1.5", name: "Currency/Exchange Clauses", parentLabelId: "1", color: "#16a34a", policyIds: ["5"] },

    // Legal
    { id: "2", name: "Legal", parentLabelId: null, color: "#ef4444", policyIds: ["6", "7", "8", "9", "10", "11", "12"] },
    { id: "2.1", name: "Jurisdiction & Governing Law", parentLabelId: "2", color: "#dc2626", policyIds: ["6"] },
    { id: "2.2", name: "Liability & Indemnity", parentLabelId: "2", color: "#dc2626", policyIds: ["7", "8"] },
    { id: "2.3", name: "Confidentiality", parentLabelId: "2", color: "#dc2626", policyIds: ["9"] },
    { id: "2.4", name: "Force Majeure", parentLabelId: "2", color: "#dc2626", policyIds: ["10"] },
    { id: "2.5", name: "Termination Clauses", parentLabelId: "2", color: "#dc2626", policyIds: ["11"] },
    { id: "2.6", name: "Arbitration & Dispute Resolution", parentLabelId: "2", color: "#dc2626", policyIds: ["12"] },

    // Compliance
    { id: "3", name: "Compliance", parentLabelId: null, color: "#f97316", policyIds: ["13", "14", "15", "16", "17", "18"] },
    { id: "3.1", name: "Data Privacy (GDPR/PCI-DSS)", parentLabelId: "3", color: "#ea580c", policyIds: ["13", "14"] },
    { id: "3.2", name: "Anti-Money Laundering (AML)", parentLabelId: "3", color: "#ea580c", policyIds: ["15"] },
    { id: "3.3", name: "Know Your Customer (KYC)", parentLabelId: "3", color: "#ea580c", policyIds: ["16"] },
    { id: "3.4", name: "Sanctions & Export Controls", parentLabelId: "3", color: "#ea580c", policyIds: ["17"] },
    { id: "3.5", name: "Ethical Conduct", parentLabelId: "3", color: "#ea580c", policyIds: ["18"] },

    // Operational
    { id: "4", name: "Operational", parentLabelId: null, color: "#3b82f6", policyIds: ["19", "20", "21", "22", "23"] },
    { id: "4.1", name: "Service Level Agreements (SLA)", parentLabelId: "4", color: "#2563eb", policyIds: ["19", "20"] },
    { id: "4.2", name: "Performance Metrics", parentLabelId: "4", color: "#2563eb", policyIds: ["21"] },
    { id: "4.3", name: "Delivery & Acceptance", parentLabelId: "4", color: "#2563eb", policyIds: ["22"] },
    { id: "4.4", name: "Maintenance Obligations", parentLabelId: "4", color: "#2563eb", policyIds: ["23"] },

    // Security
    { id: "5", name: "Security", parentLabelId: null, color: "#a855f7", policyIds: ["24", "25", "26", "27"] },
    { id: "5.1", name: "Data Encryption", parentLabelId: "5", color: "#9333ea", policyIds: ["24"] },
    { id: "5.2", name: "Access Control", parentLabelId: "5", color: "#9333ea", policyIds: ["25"] },
    { id: "5.3", name: "Security Breach Response", parentLabelId: "5", color: "#9333ea", policyIds: ["26"] },
    { id: "5.4", name: "Third-Party Security Requirements", parentLabelId: "5", color: "#9333ea", policyIds: ["27"] },

    // Risk & Audit
    { id: "6", name: "Risk & Audit", parentLabelId: null, color: "#eab308", policyIds: ["28", "29", "30", "31"] },
    { id: "6.1", name: "Insurance Coverage", parentLabelId: "6", color: "#ca8a04", policyIds: ["28"] },
    { id: "6.2", name: "Risk Assessment Clauses", parentLabelId: "6", color: "#ca8a04", policyIds: ["29"] },
    { id: "6.3", name: "Audit Rights", parentLabelId: "6", color: "#ca8a04", policyIds: ["30"] },
    { id: "6.4", name: "Reporting Obligations", parentLabelId: "6", color: "#ca8a04", policyIds: ["31"] },

    // Intellectual Property
    { id: "7", name: "Intellectual Property", parentLabelId: null, color: "#ec4899", policyIds: ["32", "33", "34"] },
    { id: "7.1", name: "IP Ownership", parentLabelId: "7", color: "#db2777", policyIds: ["32"] },
    { id: "7.2", name: "Licensing", parentLabelId: "7", color: "#db2777", policyIds: ["33"] },
    { id: "7.3", name: "Patent/Trademark Protection", parentLabelId: "7", color: "#db2777", policyIds: ["34"] },

    // Environmental & Sustainability
    { id: "8", name: "Environmental & Sustainability", parentLabelId: null, color: "#14b8a6", policyIds: ["35", "36", "37"] },
    { id: "8.1", name: "Waste Management", parentLabelId: "8", color: "#0d9488", policyIds: ["35"] },
    { id: "8.2", name: "Green Procurement", parentLabelId: "8", color: "#0d9488", policyIds: ["36"] },
    { id: "8.3", name: "ESG Commitments", parentLabelId: "8", color: "#0d9488", policyIds: ["37"] },
  ]);

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
          </div>
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
