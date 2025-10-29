# Fixella

**AI Ticket Intelligence for MSPs & IT Teams**

----

## Team
- **Team Name**: EspressoOps
- **Members**:  
  - Sneha Jain  
  - Siddhartha Chakrabarty
 
<img width="1047" height="588" alt="image" src="https://github.com/user-attachments/assets/68a3bc9b-02cb-430e-a558-a37ee84d61b5" />
    
----

## Hackathon Theme / Challenge Addressed  
**Service efficiency improvement for MSPs and IT Teams**  

----

## Short Description  
<img width="1047" height="588" alt="image" src="https://github.com/user-attachments/assets/aac1a2ba-5481-4701-9d30-75a918681853" />

A smart ticket-assistant for Managed Service Providers (MSPs) and IT teams that:

- Automatically collects ticket context
- Converts historical tickets into an AI knowledge graph
- Predicts escalations
- Provides guided, step-by-step resolution assistance to reduce escalations and speed incident resolution.

---

## Problem statement
MSPs and IT teams struggle with:

- Repeated escalations and slow resolutions.
- Loss of contextual ticket metadata (makes reproducing/resolving issues harder).
- Lack of actionable, step-by-step guidance for L1 technicians.
- Difficulty surfacing similar past tickets and proven resolution steps.

Fixella addresses these by combining telemetry collection, vector embeddings, knowledge graphing and explainable ML to reduce escalations and speed resolution.

---

## Our Solution  
<img width="1050" height="590" alt="image" src="https://github.com/user-attachments/assets/2f992b06-6a22-4ee2-92e9-1462c2d4a377" />

| Component                         | What it does                                                                                                                                                                                            |
| --------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Auto Ticket Context Collector** | Webhook triggers when a ticket is created; collects telemetry & metadata from SuperOps and stores it in S3.                                                                                             |
| **Fixella AI Agent**              | Historical tickets are converted to embeddings (Amazon Titan) and stored in OpenSearch; a master agent with sub-agents (Strands + Amazon Bedrock) provides resolution steps, chat, and screen-guidance. |
| **Knowledge Graph & Chat**        | Builds a graph (nodes/edges) of tickets, categories, steps, and assets — enables “chat with the knowledge graph” to query relationships and surface similar tickets.                                    |
| **Escalation Avoidance Engine**   | Random forest model trained on historical tickets (deployed on SageMaker); outputs and explains escalation probability using SHAP.                                                                      |
| **Fixella AssistView**            | When a technician enables screen-share, AssistView provides sub-step level instructions for a resolution.                                                                                               |

## Fixella AI Agent Workflow
<img width="1052" height="588" alt="image" src="https://github.com/user-attachments/assets/f8a90dd8-a15b-4b60-b9b3-543733f1244b" />

The Fixella AI Agent operates using a multi-agent architecture built on Strands and Amazon Bedrock (AgentCore).
Each sub-agent specializes in a specific task — from resolving tickets to guiding technicians in real time.

| **Agent**                  | **Purpose / Functionality**                                                                                                |
| -------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| **Resolution Steps Agent** | Provides resolution steps by searching for similar past tickets in **Amazon OpenSearch** and returning relevant solutions. |
| **Chat Agent**             | Answers technician queries related to the tickets using contextual knowledge and past resolutions.                         |
| **Sub-Steps Agent**        | Breaks each resolution step into finer-grained *sub-steps* to ensure step-by-step execution accuracy.                      |
| **Screen Guide Agent**     | Guides technicians in real time by analyzing the shared screen and suggesting the *next action* to take.                   |

---

## Knowledge Graph
<img width="1051" height="590" alt="image" src="https://github.com/user-attachments/assets/47b13730-9fd9-40a6-b910-50ee2932f556" />

Fixella builds a Knowledge Graph to represent the relationships between tickets, assets, categories, clients, and resolutions.
This structure allows technicians and AI agents to query, reason, and navigate across interconnected support data.

**Example Graph**: A sample node relationship for the ticket “Mouse not working”:

| **Entity**            | **Linked Entities**           | **Relation / Edge Type** |
| --------------------- | ----------------------------- | ------------------------ |
| **Mouse not working** | John Doe                      | `resolved`               |
| **Mouse not working** | XYZ Corporation               | `client`                 |
| **Mouse not working** | Hardware                      | `category`               |
| **Mouse not working** | Mouse                         | `asset`                  |
| **Mouse not working** | Hardware failure              | `root_cause`             |
| **Mouse not working** | Update mouse drivers          | `step`                   |
| **Mouse not working** | Check connections & batteries | `step`                   |
| **Mouse not working** | Clean mouse sensor            | `step`                   |
| **Mouse not working** | Mouse issues                  | `similar_to`             |
| **Mouse not working** | Low                           | `impact`                 |

**Edges & Nodes Definition**: 

| **Edge / Node Type** | **Description**                                           |
| -------------------- | --------------------------------------------------------- |
| **resolved**         | Technician resolved that ticket.                          |
| **category**         | Ticket belongs to a specific category.                    |
| **root_cause**       | Indicates the underlying cause of the issue.              |
| **asset**            | The device or component referenced in the ticket.         |
| **step**             | Links a ticket to one of its resolution or worklog steps. |
| **client**           | Represents the company or organization name.              |
| **impact**           | Denotes the severity level of the issue.                  |
| **similar_to**       | Connects tickets that are similar in nature.              |

---

## How Fixella Solves Real World Problems?
<img width="1050" height="587" alt="image" src="https://github.com/user-attachments/assets/efa59803-1a34-406c-8d7c-90b79ab630fe" />
<img width="1047" height="590" alt="image" src="https://github.com/user-attachments/assets/81c96f3c-efc9-484a-8eb4-f7e9064f9481" />

---

## Architecture Diagram 
<img width="1050" height="588" alt="image" src="https://github.com/user-attachments/assets/5e4d01e7-a1a4-41c7-91d4-daffb72917aa" />
| **Component**            | **Description**                                                                                                                                               |
| ------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Input**                | SuperOps webhook triggers data collection when a ticket is created. Metadata and telemetry are collected and stored in **AWS S3**.                            |
| **Embedding & Indexing** | Historical ticket data is embedded using **Amazon Titan** and indexed in **Amazon OpenSearch** for efficient retrieval.                                       |
| **Agents**               | **Strands + Amazon Bedrock (AgentCore)** orchestrate the master agent (*Fixella AT*) and its sub-agents for resolution generation, chat, and screen guidance. |
| **Knowledge Graph**      | Constructed using **vis-data / vis-network**, representing relationships between tickets, resolution steps, assets, and categories.                           |
| **ML Models**            | A **Random Forest model** hosted on **Amazon SageMaker** predicts escalation likelihood, while **SHAP** provides explainability for predictions.              |
| **Frontend**             | **AssistView (React)** provides an interactive UI with step-by-step guidance, chat, and visualization of the knowledge graph.                                 |

---

## Tech stack
<img width="1052" height="591" alt="image" src="https://github.com/user-attachments/assets/9e786ca0-f8f3-4630-b22f-d5bc1ca77a5a" />

| **Layer**              | **Technologies / Tools**                           |
| ---------------------- | -------------------------------------------------- |
| **Frontend**           | React, Tailwind CSS                               |
| **Backend**            | Flask, Python, SuperOps API                      |
| **Storage & Database** | Amazon DynamoDB, Amazon S3, Amazon OpenSearch    |
| **Agentic AI**         | Strands Agents, Amazon Bedrock, Amazon AgentCore |
| **Machine Learning**   | Amazon SageMaker                                   |

## Estimated Implementation Cost
<img width="1048" height="587" alt="image" src="https://github.com/user-attachments/assets/33047bae-a1ac-4d26-b984-d9556e061ccc" />

- Amazon Bedrock (LLM & embeddings): $500 – $3,000 / month
- AWS SageMaker: $1,000 – $7,500 / month
- AWS OpenSearch: $100 – $800 / month
- DynamoDB: $20 – $300 / month
- Bedrock AgentCore: $50 – $400 / month
- S3: $20 – $80 / month
  
Total estimate: $1,690 – $12,080 / month









