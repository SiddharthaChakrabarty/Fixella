# Fixella

**AI Ticket Intelligence for MSPs & IT Teams**

---

## Index

- [Team](#team)
- [Hackathon Theme / Challenge Addressed](#hackathon-theme--challenge-addressed)
- [Demo Video](#demo-video)
- [Pitch Deck](#pitch-deck)
- [How to run it](#how-to-run-it)
- [Short Description](#short-description)
- [Problem statement](#problem-statement)
- [Our Solution](#our-solution)
- [Fixella AI Agent Workflow](#fixella-ai-agent-workflow)
- [Knowledge Graph](#knowledge-graph)
- [How Fixella Solves Real World Problems?](#how-fixella-solves-real-world-problems)
- [Architecture Diagram](#architecture-diagram)
- [Tech stack](#tech-stack)
- [Estimated Implementation Cost](#estimated-implementation-cost)

---

## Team
- **Team Name**: EspressoOps
- **Members**:  
  - Sneha Jain  
  - Siddhartha Chakrabarty
 
<img width="1047" height="588" alt="image" src="https://github.com/user-attachments/assets/68a3bc9b-02cb-430e-a558-a37ee84d61b5" />
    
---

## Hackathon Theme / Challenge Addressed  
**Service efficiency improvement for MSPs and IT Teams**  

---

## Demo Video

---

## Pitch Deck

---

## How to run it

1. Clone the repo:
   ```bash
   git clone https://github.com/SiddharthaChakrabarty/Fixella.git
   cd fixella
   ```

2. Backend:
   ```bash
   cd backend
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   python app.py
   python screen_ws_server.py
   ```
     
3. Frontend:
    ```bash
   cd frontend
   npm install
   npm run dev
   ```

---

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
---

## Fixella AI Agent Workflow
<img width="7244" height="3216" alt="image" src="https://github.com/user-attachments/assets/7fba4f77-c671-4095-b9bc-5ab27543681d" />

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
<img width="3264" height="1524" alt="image" src="https://github.com/user-attachments/assets/11e58bba-ef09-4f7a-a029-b8825929b6fa" />

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

### **Scenario 1**: A & B are clients of Company M which have the same OS. Client B’s printer issue is solved.
Fixella’s AI agent analyses Client B’s ticket and suggests resolution steps according to Client A’s custom config by matching the embeddings of tickets of Client A & B. 
<img width="2488" height="1204" alt="image" src="https://github.com/user-attachments/assets/feb10b39-f31b-45de-8cf2-5966bfb15201" />

### **Scenario 2**: A is a client of Company M which has previously reported 200+ issue tickets. A new issue ticket is raised by Client A.
Fixella’s AI agent analyses Client A’s past ticket embeddings with the recent ticket and provides the best 3 solutions using the knowledge graph.
<img width="2936" height="1100" alt="image" src="https://github.com/user-attachments/assets/d8517f2a-53c2-4190-aff0-d056914a1f60" />

### **Scenario 3**: An issue ticket is received by L1 which is escalated 70% of the times previously.
Previously escalated tickets are analysed by Fixella’s AI agent and it provides a clear and detailed resolution steps to L1 to avoid escalation. 
<img width="2764" height="1096" alt="image" src="https://github.com/user-attachments/assets/c1269419-7534-4305-aa2f-adad9eb3eeb6" />

### **Scenario 4**: An issue ticket is received which has never been reported by anybody yet.
The metadata extracted by Fixella’s Auto Ticket Context Collector is sent to Fixella’s AI Agent which analyses the issue and provides proper resolution steps.
<img width="2612" height="1100" alt="image" src="https://github.com/user-attachments/assets/c589969f-52b4-439f-aee3-c50261a748b8" />

---

## Architecture Diagram 
<img width="7768" height="3888" alt="image" src="https://github.com/user-attachments/assets/c9232b08-4323-4476-9616-f4bb961e7615" />

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

---

## Comparison with other platforms
<img width="1048" height="587" alt="image" src="https://github.com/user-attachments/assets/393ad478-54ff-4c60-b140-f1b3af9f6131" />

---

## Estimated Implementation Cost
<img width="1048" height="587" alt="image" src="https://github.com/user-attachments/assets/33047bae-a1ac-4d26-b984-d9556e061ccc" />

- Amazon Bedrock (LLM & embeddings): $500 – $3,000 / month
- AWS SageMaker: $1,000 – $7,500 / month
- AWS OpenSearch: $100 – $800 / month
- DynamoDB: $20 – $300 / month
- Bedrock AgentCore: $50 – $400 / month
- S3: $20 – $80 / month
  
Total estimate: $1,690 – $12,080 / month

---



