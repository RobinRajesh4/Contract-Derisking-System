// Centralized policy library and labels for reuse across the app
// Note: Keep in sync with the Policy Library UI expectations

export type RiskLevel = "high" | "medium" | "low";

export interface UILibraryPolicy {
  id: string;
  name: string;
  description: string; // used as the policy "check" text against clauses
  riskLevel: RiskLevel;
  labelIds: string[];
}

export interface PolicyLabel {
  id: string;
  name: string;
  parentLabelId: string | null;
  color: string;
  policyIds: string[];
}

// Root domain label IDs for mapping to backend domains
export const ROOT_DOMAIN_LABELS: Record<string, string> = {
  "1": "Financial",
  "2": "Legal",
  "3": "Compliance",
  "4": "Operational",
  "5": "Security",
  "7": "Intellectual Property",
  // Map Environmental & Sustainability to "Environmental" to match LLM domain
  "8": "Environmental",
  // Others like Risk & Audit (6) don't have a direct LLM domain; we can map to Other if needed
};

export const uiPolicies: UILibraryPolicy[] = [
  { id: "1", name: "Standard Payment Terms Policy", description: "All contracts must adhere to 30-day net payment terms unless exceptional approval is obtained", riskLevel: "medium", labelIds: ["1", "1.1"] },
  { id: "2", name: "Early Payment Discount Limits", description: "Maximum discount for early payment should not exceed 2% for 10-day terms", riskLevel: "low", labelIds: ["1", "1.2"] },
  { id: "3", name: "Tax Compliance Requirements", description: "All contracts must include appropriate tax clauses compliant with local jurisdictions", riskLevel: "high", labelIds: ["1", "1.3"] },
  { id: "4", name: "Invoice Documentation Standards", description: "Invoices must include all required documentation within 5 business days", riskLevel: "medium", labelIds: ["1", "1.4"] },
  { id: "5", name: "Foreign Exchange Risk Management", description: "Contracts exceeding $100K must specify currency and exchange rate mechanisms", riskLevel: "medium", labelIds: ["1", "1.5"] },

  { id: "6", name: "Governing Law Preference", description: "Contracts should specify governing law of company's primary jurisdiction", riskLevel: "high", labelIds: ["2", "2.1"] },
  { id: "7", name: "Liability Cap Requirements", description: "Liability must be capped at contract value or annual fees, whichever is lower", riskLevel: "high", labelIds: ["2", "2.2"] },
  { id: "8", name: "Mutual Indemnification", description: "Indemnification clauses must be mutual and reasonable in scope", riskLevel: "high", labelIds: ["2", "2.2"] },
  { id: "9", name: "Confidentiality Period", description: "Confidentiality obligations must extend 3-5 years post-termination", riskLevel: "medium", labelIds: ["2", "2.3"] },
  { id: "10", name: "Force Majeure Definitions", description: "Force majeure clauses must include pandemic, natural disasters, and war", riskLevel: "medium", labelIds: ["2", "2.4"] },
  { id: "11", name: "Termination Notice Period", description: "Require minimum 60-day notice for termination without cause", riskLevel: "medium", labelIds: ["2", "2.5"] },
  { id: "12", name: "Arbitration Clause Standard", description: "Disputes should be resolved through binding arbitration in neutral jurisdiction", riskLevel: "medium", labelIds: ["2", "2.6"] },

  { id: "13", name: "GDPR Data Processing Agreement", description: "All contracts processing EU data must include GDPR-compliant DPA", riskLevel: "high", labelIds: ["3", "3.1"] },
  { id: "14", name: "PCI-DSS Compliance for Payment Data", description: "Payment processing must meet PCI-DSS Level 1 standards", riskLevel: "high", labelIds: ["3", "3.1"] },
  { id: "15", name: "AML Transaction Monitoring", description: "Implement real-time monitoring for transactions exceeding $10K", riskLevel: "high", labelIds: ["3", "3.2"] },
  { id: "16", name: "KYC Customer Verification", description: "Complete identity verification required for all new business relationships", riskLevel: "high", labelIds: ["3", "3.3"] },
  { id: "17", name: "Sanctions Screening Requirements", description: "Screen all parties against OFAC and international sanctions lists", riskLevel: "high", labelIds: ["3", "3.4"] },
  { id: "18", name: "Code of Conduct Compliance", description: "All vendors must acknowledge and comply with company code of conduct", riskLevel: "medium", labelIds: ["3", "3.5"] },

  { id: "19", name: "Uptime SLA Requirements", description: "Critical services must guarantee 99.9% uptime with penalties for breaches", riskLevel: "high", labelIds: ["4", "4.1"] },
  { id: "20", name: "Response Time Standards", description: "Support response times: Critical-1hr, High-4hr, Medium-24hr", riskLevel: "medium", labelIds: ["4", "4.1"] },
  { id: "21", name: "Performance Measurement KPIs", description: "Establish clear KPIs and quarterly performance reviews", riskLevel: "medium", labelIds: ["4", "4.2"] },
  { id: "22", name: "Delivery Timeline Requirements", description: "Deliverables must have defined acceptance criteria and timelines", riskLevel: "medium", labelIds: ["4", "4.3"] },
  { id: "23", name: "Preventive Maintenance Schedule", description: "Critical systems require quarterly preventive maintenance windows", riskLevel: "low", labelIds: ["4", "4.4"] },

  { id: "24", name: "Data Encryption Standards", description: "All data must be encrypted using AES-256 at rest and TLS 1.3 in transit", riskLevel: "high", labelIds: ["5", "5.1"] },
  { id: "25", name: "Multi-Factor Authentication", description: "MFA required for all administrative and privileged access", riskLevel: "high", labelIds: ["5", "5.2"] },
  { id: "26", name: "Security Incident Notification", description: "Security breaches must be reported within 24 hours of discovery", riskLevel: "high", labelIds: ["5", "5.3"] },
  { id: "27", name: "Third-Party Security Assessment", description: "Vendors must provide SOC 2 Type II or ISO 27001 certification", riskLevel: "high", labelIds: ["5", "5.4"] },

  { id: "28", name: "Minimum Insurance Coverage", description: "Vendors must maintain $5M general liability and $2M cyber insurance", riskLevel: "high", labelIds: ["6", "6.1"] },
  { id: "29", name: "Risk Assessment Frequency", description: "Conduct comprehensive risk assessments annually or upon major changes", riskLevel: "medium", labelIds: ["6", "6.2"] },
  { id: "30", name: "Audit Access Rights", description: "Company reserves right to audit vendor compliance with 30-day notice", riskLevel: "medium", labelIds: ["6", "6.3"] },
  { id: "31", name: "Monthly Compliance Reporting", description: "Vendors must provide monthly compliance and performance reports", riskLevel: "low", labelIds: ["6", "6.4"] },

  { id: "32", name: "IP Ownership Clarity", description: "All custom work product and IP must be explicitly assigned to company", riskLevel: "high", labelIds: ["7", "7.1"] },
  { id: "33", name: "License Grant Restrictions", description: "Third-party licenses must be perpetual, non-exclusive, and transferable", riskLevel: "medium", labelIds: ["7", "7.2"] },
  { id: "34", name: "Patent Indemnification", description: "Vendors must indemnify against patent infringement claims", riskLevel: "high", labelIds: ["7", "7.3"] },

  { id: "35", name: "Waste Reduction Targets", description: "Vendors must demonstrate commitment to reduce waste by 20% annually", riskLevel: "low", labelIds: ["8", "8.1"] },
  { id: "36", name: "Sustainable Sourcing Requirements", description: "Priority given to vendors with certified sustainable supply chains", riskLevel: "low", labelIds: ["8", "8.2"] },
  { id: "37", name: "ESG Reporting Standards", description: "Annual ESG metrics reporting required for contracts over $500K", riskLevel: "medium", labelIds: ["8", "8.3"] },
];

export const uiLabels: PolicyLabel[] = [
  { id: "1", name: "Financial", parentLabelId: null, color: "#22c55e", policyIds: ["1", "2", "3", "4", "5"] },
  { id: "1.1", name: "Payment Terms", parentLabelId: "1", color: "#16a34a", policyIds: ["1"] },
  { id: "1.2", name: "Pricing & Discounts", parentLabelId: "1", color: "#16a34a", policyIds: ["2"] },
  { id: "1.3", name: "Taxation", parentLabelId: "1", color: "#16a34a", policyIds: ["3"] },
  { id: "1.4", name: "Invoicing", parentLabelId: "1", color: "#16a34a", policyIds: ["4"] },
  { id: "1.5", name: "Currency/Exchange Clauses", parentLabelId: "1", color: "#16a34a", policyIds: ["5"] },

  { id: "2", name: "Legal", parentLabelId: null, color: "#ef4444", policyIds: ["6", "7", "8", "9", "10", "11", "12"] },
  { id: "2.1", name: "Jurisdiction & Governing Law", parentLabelId: "2", color: "#dc2626", policyIds: ["6"] },
  { id: "2.2", name: "Liability & Indemnity", parentLabelId: "2", color: "#dc2626", policyIds: ["7", "8"] },
  { id: "2.3", name: "Confidentiality", parentLabelId: "2", color: "#dc2626", policyIds: ["9"] },
  { id: "2.4", name: "Force Majeure", parentLabelId: "2", color: "#dc2626", policyIds: ["10"] },
  { id: "2.5", name: "Termination Clauses", parentLabelId: "2", color: "#dc2626", policyIds: ["11"] },
  { id: "2.6", name: "Arbitration & Dispute Resolution", parentLabelId: "2", color: "#dc2626", policyIds: ["12"] },

  { id: "3", name: "Compliance", parentLabelId: null, color: "#f97316", policyIds: ["13", "14", "15", "16", "17", "18"] },
  { id: "3.1", name: "Data Privacy (GDPR/PCI-DSS)", parentLabelId: "3", color: "#ea580c", policyIds: ["13", "14"] },
  { id: "3.2", name: "Anti-Money Laundering (AML)", parentLabelId: "3", color: "#ea580c", policyIds: ["15"] },
  { id: "3.3", name: "Know Your Customer (KYC)", parentLabelId: "3", color: "#ea580c", policyIds: ["16"] },
  { id: "3.4", name: "Sanctions & Export Controls", parentLabelId: "3", color: "#ea580c", policyIds: ["17"] },
  { id: "3.5", name: "Ethical Conduct", parentLabelId: "3", color: "#ea580c", policyIds: ["18"] },

  { id: "4", name: "Operational", parentLabelId: null, color: "#3b82f6", policyIds: ["19", "20", "21", "22", "23"] },
  { id: "4.1", name: "Service Level Agreements (SLA)", parentLabelId: "4", color: "#2563eb", policyIds: ["19", "20"] },
  { id: "4.2", name: "Performance Metrics", parentLabelId: "4", color: "#2563eb", policyIds: ["21"] },
  { id: "4.3", name: "Delivery & Acceptance", parentLabelId: "4", color: "#2563eb", policyIds: ["22"] },
  { id: "4.4", name: "Maintenance Obligations", parentLabelId: "4", color: "#2563eb", policyIds: ["23"] },

  { id: "5", name: "Security", parentLabelId: null, color: "#a855f7", policyIds: ["24", "25", "26", "27"] },
  { id: "5.1", name: "Data Encryption", parentLabelId: "5", color: "#9333ea", policyIds: ["24"] },
  { id: "5.2", name: "Access Control", parentLabelId: "5", color: "#9333ea", policyIds: ["25"] },
  { id: "5.3", name: "Security Breach Response", parentLabelId: "5", color: "#9333ea", policyIds: ["26"] },
  { id: "5.4", name: "Third-Party Security Requirements", parentLabelId: "5", color: "#9333ea", policyIds: ["27"] },

  { id: "6", name: "Risk & Audit", parentLabelId: null, color: "#eab308", policyIds: ["28", "29", "30", "31"] },
  { id: "6.1", name: "Insurance Coverage", parentLabelId: "6", color: "#ca8a04", policyIds: ["28"] },
  { id: "6.2", name: "Risk Assessment Clauses", parentLabelId: "6", color: "#ca8a04", policyIds: ["29"] },
  { id: "6.3", name: "Audit Rights", parentLabelId: "6", color: "#ca8a04", policyIds: ["30"] },
  { id: "6.4", name: "Reporting Obligations", parentLabelId: "6", color: "#ca8a04", policyIds: ["31"] },

  { id: "7", name: "Intellectual Property", parentLabelId: null, color: "#ec4899", policyIds: ["32", "33", "34"] },
  { id: "7.1", name: "IP Ownership", parentLabelId: "7", color: "#db2777", policyIds: ["32"] },
  { id: "7.2", name: "Licensing", parentLabelId: "7", color: "#db2777", policyIds: ["33"] },
  { id: "7.3", name: "Patent/Trademark Protection", parentLabelId: "7", color: "#db2777", policyIds: ["34"] },

  { id: "8", name: "Environmental & Sustainability", parentLabelId: null, color: "#14b8a6", policyIds: ["35", "36", "37"] },
  { id: "8.1", name: "Waste Management", parentLabelId: "8", color: "#0d9488", policyIds: ["35"] },
  { id: "8.2", name: "Green Procurement", parentLabelId: "8", color: "#0d9488", policyIds: ["36"] },
  { id: "8.3", name: "ESG Commitments", parentLabelId: "8", color: "#0d9488", policyIds: ["37"] },
];
