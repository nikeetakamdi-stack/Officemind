# OfficeMind

An AI workplace assistant that runs entirely on your own computer. No data leaves your machine and no paid API is needed.

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

Coming later: Helpdesk, Onboarding and Dashboard modules.

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
├── app.py                         home page (welcome screen)
├── .streamlit/config.toml         dark theme colours
├── assets/
│   ├── style.css                  the look: cards, chat bubbles, animations
│   └── welcome.json               the Lottie welcome animation
├── pages/
│   ├── 0_Login.py                 login + sign-up page
│   └── 1_Knowledge_Assistant.py   upload + chat page
├── core/                          shared code every module uses
│   ├── auth.py                    sign up, log in, password hashing
│   ├── config.py                  all settings (models, chunk size, ...)
│   ├── database.py                opens the SQLite user database
│   ├── llm.py                     talks to Ollama
│   ├── ui.py                      shared styles, sidebar menu, typing effect
│   └── vector_store.py            opens the ChromaDB database
├── modules/
│   └── knowledge/
│       ├── pdf_loader.py          reads and splits PDFs
│       └── assistant.py           save, delete, search and answer
├── data/                          the database is saved here (not uploaded to GitHub)
└── requirements.txt               Python packages to install
```

To add a new module (for example, helpdesk), create `modules/helpdesk/` and a page `pages/2_Helpdesk.py`.

## Privacy

The document database (`data/chroma/`), the user database (`data/officemind.db`), PDF files and `.env` secret files are listed in `.gitignore`, so they are never uploaded to GitHub.
