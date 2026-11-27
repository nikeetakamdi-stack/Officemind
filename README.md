# OfficeMind

An AI workplace assistant that runs entirely on your own computer. No data leaves your machine and no paid API is needed.

## Design

A professional, enterprise-style interface with OfficeMind's own logo (a deep-blue tile with a white "O" and a light-blue spark).
- Clean light theme by default, with a **Dark mode** switch in the profile menu.
- One brand colour (deep blue `#1F4FB5`) with neutral greys, the Inter / Segoe UI font, and a clear text-size hierarchy.
- A top bar with the logo, a **search box** (tickets, documents, onboarding tasks, pages), a **notification bell** and a **profile menu**.
- A collapsible sidebar with an icon for each page; the current page is highlighted.
- Cards, buttons, forms, tables, badges and charts share one design system in `assets/style.css` (dark colours in `assets/dark.css`).
- Subtle motion only: page fade-in, hover effects and grey "skeleton" placeholders while things load.
- Friendly empty states and plain-language error messages.

## Security

- **Access levels:** every document is Public, Department-only or Confidential. The AI only searches documents the signed-in person may see. Only admins upload, delete, change access or export.
- **Sign-in:** strong passwords (10+ characters, letter, number, symbol); 5 wrong passwords lock the account for 15 minutes; automatic sign-out after 30 minutes without activity.
- **Data protection:** phone numbers, emails, Aadhaar, PAN and bank numbers are shown as `****` in AI answers; ticket text, replies, AI questions, activity details, alerts and emails are encrypted in the database; prompt tricks ("ignore your rules…") are refused.
- **Screen protection:** a watermark with the viewer's name, email and time; copy, right-click and printing are blocked; the page blurs when the window isn't active.
- **Secure mode (optional, admin switch):** with the user's consent, the webcam and a YOLO model check that no phone is pointed at the screen while Confidential answers are allowed. Frames are checked on this computer and never saved.
- **Monitoring:** an admin-only Security page with alerts, the activity log, users and settings.

**Back up `data/secret.key`.** It's the encryption key; without it, encrypted data can't be read. It's never uploaded to GitHub.

**Secure mode model:** `models/yolov8n.onnx` isn't on GitHub (12 MB, AGPL-3.0). To create it once, in a separate environment:
```
pip install ultralytics onnx onnxslim
python -c "from ultralytics import YOLO; YOLO('yolov8n.pt').export(format='onnx', opset=12, simplify=True)"
```
Then copy `yolov8n.onnx` into the `models/` folder. OfficeMind runs it with onnxruntime (no PyTorch needed).

**Limits:** these features make leaks harder and traceable. They can't stop a camera pointed at the screen, screen recorders, browser developer tools, or someone with access sharing content themselves. Uploaded PDF text in the search store (`data/chroma`) isn't encrypted, so protect the computer itself.

## Team Chat

- `#general` (everyone), channels admins create (e.g. `#it`, `#hr`) with chosen members, and one-to-one chats.
- Text, images and files (up to 10 MB); replies, pinned messages, search, read ticks (✓ sent, ✓✓ read), online/offline, unread badges.
- Voice and video calls with **Jitsi Meet** in a private, random room per call; "call started/ended" appears in the chat.
- Messages and file names are encrypted in the database, attachments are encrypted on disk (`data/chat_files/`), and only members can read a chat. Chats and calls appear in the Activity Log (without message text).
- **Limits:** new messages appear within ~3 seconds (Streamlit checks regularly, it isn't instant); no "typing…" indicator, because Streamlit can't see keystrokes until a message is sent; calls run on the Jitsi server (`meet.jit.si` by default, which may ask the first person to sign in and limits embedded calls), so set `OFFICEMIND_JITSI` to your own Jitsi server to keep calls inside the company; screen sharing needs **New window**, because browsers block it inside embedded frames.

## What it does

**Knowledge Assistant** (Phase 1, Step 1)
- Upload PDF files, such as company policies, in a web page.
- Ask questions in a chat box. The answers come **only** from your uploaded documents.
- Every answer shows which file and page it came from.
- Remove a document with its 🗑️ button, and the assistant stops using it.

**Login and roles** (Phase 1, Step 2)
- Sign up and log in. Passwords are stored as secure hashes, never as plain text.
- The **first** account created becomes the **admin**; everyone after is an **employee**.
- Admins can upload and delete PDFs. Employees can ask questions.

**Helpdesk** (Phase 2, Step 1)
- Employees raise tickets (title, description, category) and follow their status and replies.
- Admins see every ticket, move it Open → In Progress → Closed, and reply.
- Tickets are stored in the same SQLite database as the users.

**Helpdesk AI** (Phase 2, Step 2)
- Before submitting, the AI suggests a category and urgency (Low / Medium / High); the employee can change them.
- It warns "Similar issue already reported" when an open ticket describes the same problem.
- It suggests a possible fix from past closed tickets with admin replies and from the uploaded documents, and shows the original text it's based on.
- Admins see an urgency tag on every ticket, with High urgency first.
- The similarity cut-offs are in `core/config.py` (`SIMILAR_TICKET_MIN`, `SOLVED_TICKET_MIN`).

**Onboarding** (Phase 3)
- Admins build checklists of tasks (title, short description, optional link to an uploaded PDF) and assign them to new employees.
- Admins see everyone's progress in a table, with a "Needs a nudge" list of people who are stuck
  (nothing ticked for 3 days; change `ONBOARDING_STUCK_DAYS` in `core/config.py`).
- Employees tick tasks off with an animated progress bar, get a small celebration when they finish,
  and can ask the AI assistant questions on the same page.
- Uploaded PDFs are now also kept as files in `data/uploads/` (not uploaded to GitHub), so tasks can link to them.

**Manager dashboard** (Phase 4, admins only)
- Stat cards: total tickets, open tickets, average time to close, documents, employees onboarding.
- Interactive Plotly charts: tickets over time, by category, by urgency, and onboarding progress.
- Most-asked AI questions, and **unanswered questions** (what the AI couldn't find, so you know which documents to add).
- Date filter (last 7 days, 30 days, all time) and **Export to Excel** (one sheet per section).
- Questions asked to the AI and ticket close times are now recorded for this.

## How it works

1. Your PDF's text is cut into small pieces.
2. Each piece is turned into numbers (an "embedding") by the `nomic-embed-text` model and saved in a **ChromaDB** database.
3. When you ask a question, ChromaDB finds the pieces closest in meaning.
4. The **llama3.2** model (run by **Ollama**) writes an answer using only those pieces.

## Requirements

- Windows, macOS or Linux
- [Python 3.10 or newer](https://www.python.org/downloads/)
- [Ollama](https://ollama.com/download)

## Installation

1. Download the two AI models:
   ```
   ollama pull llama3.2
   ollama pull nomic-embed-text
   ```
2. Get the code:
   ```
   git clone https://github.com/<your-username>/officemind.git
   cd officemind
   ```
3. Create a virtual environment and turn it on:
   ```
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1        # Windows PowerShell
   source .venv/bin/activate           # macOS / Linux
   ```
4. Install the Python packages:
   ```
   pip install -r requirements.txt
   ```

## Running it

Make sure Ollama is running, then, **from inside the `officemind` folder** (so the dark theme loads):
```
streamlit run app.py
```
Your browser opens at http://localhost:8501. Click **Knowledge Assistant**, upload a PDF in the sidebar, click **Add to knowledge base**, and ask a question.

> Tip: after changing files in `core/` or `modules/`, stop the app with Ctrl+C and start it again. Streamlit only reloads page files on its own.

## Project structure

```
officemind/
├── app.py                         home page (greeting, quick stats, shortcuts)
├── .streamlit/config.toml         light theme and brand colour
├── assets/
│   ├── style.css                  the design system: colours, cards, tables, badges, motion
│   ├── dark.css                   dark mode colours
│   └── logo.png                   OfficeMind logo (browser tab icon)
├── pages/
│   ├── 0_Login.py                 login + sign-up page
│   ├── 1_Knowledge_Assistant.py   upload + chat page
│   ├── 2_Helpdesk.py              tickets page
│   ├── 3_Onboarding.py            checklists, progress and assistant
│   ├── 4_Dashboard.py             manager dashboard (admins only)
│   └── 5_Search.py                search results (opened from the top bar)
├── core/                          shared code every module uses
│   ├── auth.py                    sign up, log in, password hashing
│   ├── config.py                  all settings (models, chunk size, ...)
│   ├── database.py                opens the SQLite user database
│   ├── llm.py                     talks to Ollama
│   ├── ui.py                      page shell (top bar, sidebar) and shared building blocks
│   └── vector_store.py            opens the ChromaDB database
├── modules/
│   ├── knowledge/
│   │   ├── pdf_loader.py          reads and splits PDFs
│   │   ├── assistant.py           save, delete, search and answer
│   │   └── question_log.py        remembers questions asked to the AI
│   ├── dashboard/
│   │   └── metrics.py             dashboard numbers and the Excel export
│   ├── helpdesk/
│   │   ├── tickets.py             create, list, update and reply to tickets
│   │   └── ai.py                  category/urgency, similar tickets, possible fix
│   ├── onboarding/
│   │   └── checklists.py          checklists, tasks, assignments and progress
│   ├── home.py                    quick stats for the home page
│   ├── notifications.py           what the notification bell shows
│   └── search.py                  the search box
├── data/                          the database is saved here (not uploaded to GitHub)
└── requirements.txt               Python packages to install
```

To add a new module (for example, helpdesk), create `modules/helpdesk/` and a page `pages/2_Helpdesk.py`.

## Privacy

The document database (`data/chroma/`), the user database (`data/officemind.db`), PDF files and `.env` secret files are listed in `.gitignore`, so they are never uploaded to GitHub.
