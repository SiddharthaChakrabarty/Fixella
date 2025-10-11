import { Zap, ServerCog, Clock, ShieldCheck, Monitor } from "lucide-react";

export const features = [
    {
      title: "Auto Ticket Context Collector",
      icon: ServerCog,
      tag: "Webhook / Metadata",
      desc:
        "Automatically collects ticket metadata from SuperOps at creation — full history, impacted assets, priority and context available to technicians instantly.",
      bullets: [
        "Payload parsing & enrichment",
        "Links back to original SuperOps ticket",
        "Custom fields & tags"
      ]
    },
    {
      title: "Fixella AI Agent",
      icon: Zap,
      tag: "Knowledge Graph + Embeddings",
      desc:
        "Bedrock-deployed AI converts ticket history into embeddings and builds a knowledge graph to surface similar tickets and context-aware resolution steps.",
      bullets: ["Similarity scoring", "Suggested resolution steps", "Continuous learning"]
    },
    {
      title: "Technician Time Assistant",
      icon: Clock,
      tag: "Auto Billing Hours",
      desc:
        "Analyzes technician activity and deduces time spent per issue to auto-suggest billable hours — reduces admin work and improves accuracy.",
      bullets: ["Idle/Active detection", "Per-ticket time breakdown", "Exportable billing reports"]
    },
    {
      title: "Escalation Avoidance Engine",
      icon: ShieldCheck,
      tag: "ML-powered Guidance",
      desc:
        "Predicts escalation probability and provides L1 technicians with structured, prioritized steps to avoid ticket escalation.",
      bullets: ["Risk score & rationale", "Step-by-step mitigation", "Customizable policies"]
    },
    {
      title: "Screen Sharing + Guided Steps",
      icon: Monitor,
      tag: "Remote Control",
      desc:
        "A secure screen sharing flow where technicians guide users with on-screen highlights and exact click-by-click instructions.",
      bullets: ["Secure session tokens", "On-screen overlays & hints", "Recordable sessions for training"]
    }
  ];