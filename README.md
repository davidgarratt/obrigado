# Obrigado (Personal Obligation & Project Assistant)

Obrigado is an AI-powered cognitive assistant designed to solve the problem of remembering obligations, managing mental load, and tracking personal and work projects.

It allows you to dump raw, unstructured notes or voice memos, automatically ingests them using **Gemini 3.8 Flash** and **Gemini Embedding 2**, transforms them into an **interactive Knowledge Graph**, applies **decision-theoretic prioritization** (Eisenhower Matrix + Graph Centrality), produces **Morning & Evening briefings**, and schedules entries to **Google Calendar**.

Built to run seamlessly on a cloud VPS over your private **Tailscale** mesh network.

---

## 🌟 Key Capabilities

### 1. Zero-Friction Quick Ingestion & Active Elicitation
- **Text Brain Dump**: Rapid capture with `Ctrl + Enter` instant submission.
- **Active Record Elicitation**: When a note is sparse, ambiguous, or missing critical fields (such as a target deadline, concrete next action, or project context), Obrigado uses Gemini to generate 1-click elicitation questions. Answering immediately refines and locks in the record!
- **Native Multimodal Voice Memos**: Uses browser audio recording or audio file upload (`.m4a`, `.wav`, `.mp3`, `.webm`) fed directly to Gemini 3.8 Flash for audio listening and semantic extraction in one step.
- **REST Webhook**: Simple `POST /api/notes/capture` endpoint compatible with iOS Shortcuts, Raycast, Alfred, or Telegram bots.

### 2. People & Relationship Memory Hub
- **Remember the People Involved**: Automatically extracts profiles for any people mentioned in your notes (colleagues, managers, clients, family, doctors).
- **Personal Memory Bank**: Logs key memories, context facts, preferences, and personal details (e.g. *"prefers email over slack"*, *"has twins: Leo & Mia"*, *"met at DevOps 2024"*).
- **Mutual Commitments & Loop Tracking**:
  - *What you are waiting on them for* (blocked obligations).
  - *What you have promised to them* (active obligations).
- **Person Dossiers**: Interactive CRM dossiers accessible in the UI with a complete timeline of interactions and connected projects.

### 3. Dual Engine: Gemini & OpenRouter Integration
- **Gemini 3.8 Flash & Gemini Embedding 2**: Native multimodal audio listening, instant 3072-dimensional vector indexing, and fast entity resolution.
- **OpenRouter Account Support**: Connect your OpenRouter token to leverage reasoning and decision models such as **Claude 3.5 / 3.7 Sonnet**, **DeepSeek R1**, or **Llama 3.3 70B**.
- **Hybrid Auto-Fallback**: If OpenRouter is enabled, text triage and record refinement can be routed to your chosen OpenRouter model with seamless automatic fallback to Gemini if rate limits occur. Voice memos and high-dim embeddings continue to leverage Gemini natively.

### 4. Knowledge & Obligation Graph
- Structured SQLite graph store with WAL mode (Write-Ahead Logging).
- **Entity Types**:
  - `Obligation`: Actionable tasks, commitments, and deadlines.
  - `Project`: Work or personal umbrella initiatives.
  - `Person`: Stakeholders, colleagues, family, doctors.
  - `Event`: Scheduled appointments, calendar events.
  - `Organization`: Vendors, institutions, clients.
- **Relationships**:
  - `PART_OF`: Obligation $\rightarrow$ Project.
  - `DEPENDS_ON`: Task $B$ cannot start until Task $A$ is completed.
  - `WAITING_ON`: Obligation waiting on feedback from a Person.
  - `ASSIGNED_TO`: Obligation delegated to a team member.
- **Interactive 2D Force-Directed Visualizer**: Real-time interactive network explorer powered by Vis.js.

### 3. Decision Models & Reasoning Engine
- **Multi-Attribute Utility Theory (MAUT)**:
  - **Urgency Decay**: Temporal proximity modeling calculating hours remaining to deadlines.
  - **Graph Fan-Out Boost**: Automatically boosts importance when multiple downstream tasks or projects are blocked by an obligation.
  - **Eisenhower Quadrants**: Classifies all obligations into:
    - **Q1: Do First** (Urgent & Important)
    - **Q2: Schedule** (High-leverage Strategic Focus)
    - **Q3: Delegate / Quick Poke** (Urgent & Not Important)
    - **Q4: Backlog & Someday** (Low Urgency & Importance)
- **Action & Calendar Triage Decision Model**:
  - Fixed time appointments $\rightarrow$ **Direct Calendar Event**.
  - High cognitive load Q1 tasks $\rightarrow$ **Dedicated Focus Blocks**.
  - Hard deadlines without times $\rightarrow$ **All-day Morning Milestone**.
  - Soft tasks $\rightarrow$ Kept in graph to eliminate calendar clutter.
  - Every decision is logged to the `decision_logs` audit trail for full transparency.

### 4. Proactive Nudges & Anomaly Sweeps
- **Unblocked Cascade Detection**: When you complete a prerequisite task, MindGraph automatically detects dependent tasks that are now ready and prompts you.
- **Waiting-On Stalemate Detection**: Prompts you when an item has been waiting on someone for $> 48$ hours.
- **Stale Project Alerts**: Flags active projects with no progress or obligation updates for $> 5$ days.
- **Impending Deadline Radar**: Surfaces warnings for items due within 24 hours.

### 5. Start-of-Day & End-of-Day Briefings
- **Start-of-Day (Morning Kickoff)**:
  - Integrates today's Google Calendar appointments.
  - Highlights the Top 3 must-win Eisenhower Q1/Q2 obligations.
  - Flags people you need to follow up with.
  - Recommends an optimal focus block structure around your meetings.
- **End-of-Day (Evening Debrief)**:
  - Celebrates completed wins and checked-off obligations.
  - Shame-free rollover assessment for overdue items.
  - Graph hygiene check-in questions to close open cognitive loops.
  - Runs automatically on schedule (e.g., 08:00 and 19:30) or on-demand with one click.

### 6. Google Calendar Integration
- Live 2-way integration using official Google Calendar API (`v3`).
- **Offline / Staging Fallback**: Works immediately out of the box even before configuring Google OAuth credentials, staging events locally and offering instant `.ics` download files.

---

## 🚀 Quick Start Guide

### 1. Requirements
- Python 3.10+
- A Google Gemini API key (from [Google AI Studio](https://aistudio.google.com/))

### 2. Setup
```bash
# Clone or navigate to directory
cd note_taking_pa

# Install dependencies
pip install -r requirements.txt

# Configure your environment
cp .env.example .env
# Edit .env and set your GEMINI_API_KEY
```

### 3. Launch MindGraph PA
```bash
python run.py
```
Open your browser to: **`http://localhost:8000`**

---

## 🔒 Cloud VPS & Tailscale Deployment

MindGraph PA is built to run on a cloud VPS (Hetzner, DigitalOcean, Linode, AWS EC2) and be accessed securely over your private **Tailscale** mesh.

### Option A: Tailscale Serve (Automatic HTTPS & Let's Encrypt)
On your VPS with Tailscale installed:
```bash
# 1. Run MindGraph in background (or via systemd / docker)
python run.py &

# 2. Expose securely to your Tailscale network with HTTPS
tailscale serve --bg 8000
```
You can now access your assistant on any device (phone, laptop, iPad) on your Tailscale network at:
```
https://<your-vps-hostname>.<your-tailnet>.ts.net
```
No ports exposed to the public internet, no complex reverse proxies, full TLS encryption!

### Option B: Docker Compose
```bash
docker compose up -d
```

### Option C: Linux Systemd Service
```bash
sudo cp mindgraph.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now mindgraph
```

---

## 📅 Google Calendar OAuth Setup (Optional)

1. Open [Google Cloud Console](https://console.cloud.google.com/).
2. Create a project and enable the **Google Calendar API**.
3. Under **APIs & Services > Credentials**, create an **OAuth 2.0 Client ID** (Web application).
4. Set Authorized Redirect URI to:
   ```
   https://<your-vps-hostname>.<your-tailnet>.ts.net/api/calendar/oauth-callback
   ```
5. Download JSON and save as `data/credentials.json`.
6. Go to the Settings tab in the MindGraph UI and click "Link Google Calendar".

---

## 📱 Mobile Quick Capture (iOS Shortcuts & Android)

You can capture thoughts from your phone's lockscreen or action button using iOS Shortcuts or HTTP Shortcuts:

- **Method**: `POST`
- **URL**: `https://<your-vps>.<your-tailnet>.ts.net/api/notes/capture`
- **Headers**: `Content-Type: application/json`
- **Body**:
  ```json
  {
    "content": "Dictated note from phone",
    "source_type": "text",
    "auto_sync_calendar": true
  }
  ```

---

## 🧪 Architecture Overview

```
                               ┌─────────────────────────────────┐
                               │  Quick Capture (Text / Voice)   │
                               └────────────────┬────────────────┘
                                                │
                                                ▼
                             ┌─────────────────────────────────────┐
                             │  Gemini 3.8 Flash & Embeddings      │
                             │  - Entity Resolution                │
                             │  - Temporal Parsing (ISO Times)     │
                             │  - Relationship Extraction          │
                             └──────────────────┬──────────────────┘
                                                │
                                                ▼
                             ┌─────────────────────────────────────┐
                             │     Decision Engine & Reasoning     │
                             │  - Eisenhower MAUT Urgency/Import.  │
                             │  - Graph Centrality Fan-out Boost   │
                             │  - Action & Calendar Triage Model   │
                             └──────────┬──────────────────────────┘
                                        │
                 ┌──────────────────────┼──────────────────────┐
                 ▼                      ▼                      ▼
      ┌────────────────────┐ ┌────────────────────┐ ┌────────────────────┐
      │  Knowledge Graph   │ │   Google Calendar  │ │  Daily Briefings   │
      │  - Obligations     │ │  - Fixed Events    │ │  - Morning Kickoff │
      │  - Projects        │ │  - Focus Blocks    │ │  - Evening Debrief │
      │  - People/Blockers │ │  - Milestones      │ │  - Proactive Nudges│
      └────────────────────┘ └────────────────────┘ └────────────────────┘
```
