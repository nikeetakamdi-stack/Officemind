"""Security scan for code: secrets, injection and unsafe input, and risky or outdated libraries.

Everything here is an exact pattern check (no AI), so a result is always backed by
something really in the code. The other way round isn't true: a pattern scan can't
find every vulnerability, and it can't see which library *versions* you install
(there's no internet lookup). For that, run `pip-audit` or `npm audit` in your project.

Secrets found are hidden (****) everywhere OfficeMind shows or saves the code,
and are never sent to the AI.
"""

import ast
import re

from modules.codereview.checks import blank_comments_and_strings, finding, sql_statements

REDACTED = "****"

# ---------- Secrets ----------
SECRET_PATTERNS = [
    ("private key", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY(?: BLOCK)?-----[\s\S]*?(?:-----END[^-]*-----|$)")),
    ("AWS access key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("GitHub token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b")),
    ("Slack token", re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}\b")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("Stripe key", re.compile(r"\b(?:sk|rk)_(?:live|test)_[0-9a-zA-Z]{16,}\b")),
    ("AI service key", re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{20,}\b")),
    ("JWT token", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")),
    ("password in a connection string", re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s:/@'\"]+:([^\s@/'\"]{3,})@", re.IGNORECASE)),
]
NAME_WORDS = r"(?:password|passwd|pwd|pass|secret|api[_-]?key|apikey|access[_-]?key|private[_-]?key|token|auth[_-]?token|client[_-]?secret|credentials?)"
# password = "abc", "apiKey": "abc", String token = "abc", PASSWORD := 'abc'
ASSIGNED = re.compile(
    rf"""(?ix)\b([\w.\-\[\]'"]*{NAME_WORDS}[\w\-\]'"]*)\s*(?:=|:=|:|==)\s*(?:[frbu]{{0,2}})(["'`])([^"'`\n]{{4,}})\2""")
SQL_PASSWORD = re.compile(r"(?i)\b(?:IDENTIFIED\s+BY|PASSWORD\s*=?)\s+(['\"])([^'\"\n]{3,})\1")
PLACEHOLDER = re.compile(r"(?i)^(\*+|x{3,}|\.{3,}|<.*>|\$\{.*\}|\{\{.*\}\}|%\(.*\)s|%s|your[_ -].*|change[_ -]?me|"
                         r"example.*|dummy.*|placeholder.*|none|null|test|password|secret|token|env|redacted)$")


def find_secrets(code: str) -> list[dict]:
    """[{"line", "kind", "value", "start", "end"}] for every secret in the code."""
    found = []
    for kind, pattern in SECRET_PATTERNS:
        for m in pattern.finditer(code):
            group = 1 if pattern.groups else 0
            found.append({"kind": kind, "start": m.start(group), "end": m.end(group)})
    for m in ASSIGNED.finditer(code):
        value = m.group(3).strip()
        if not PLACEHOLDER.match(value) and not re.match(r"(?i)^(os\.|process\.env|System\.getenv)", value):
            found.append({"kind": "hard-coded " + ("password" if re.search(r"(?i)pass|pwd", m.group(1)) else "secret"),
                          "start": m.start(3), "end": m.end(3)})
    for m in SQL_PASSWORD.finditer(code):
        if not PLACEHOLDER.match(m.group(2)):
            found.append({"kind": "hard-coded password", "start": m.start(2), "end": m.end(2)})
    found.sort(key=lambda s: (s["start"], -(s["end"] - s["start"])))
    unique, last_end = [], -1
    for s in found:  # the same text found by two patterns counts once
        if s["start"] >= last_end:
            s["line"] = code.count("\n", 0, s["start"]) + 1
            s["value"] = code[s["start"]:s["end"]]
            unique.append(s)
            last_end = s["end"]
    return unique


def redact(code: str, secrets: list[dict] | None = None) -> str:
    """The code with every secret replaced by ****. Used before saving it or sending it to the AI."""
    secrets = find_secrets(code) if secrets is None else secrets
    for s in sorted(secrets, key=lambda s: s["start"], reverse=True):
        hidden = REDACTED + "\n" * code.count("\n", s["start"], s["end"])  # keep line numbers the same
        code = code[:s["start"]] + hidden + code[s["end"]:]
    return code


def preview(value: str) -> str:
    """Show only the first 2 characters: 'sk****'."""
    return (value[:2] if len(value) > 6 else "") + REDACTED


def secret_findings(secrets: list[dict]) -> list[dict]:
    return [finding(s["line"], "critical", "security",
                    f"A {s['kind']} is written in the code ({preview(s['value'])}). Anyone who can see the code "
                    "(or its history in Git) can use it.",
                    "Remove it, change (rotate) it, and read it from an environment variable or a secrets manager, "
                    "e.g. `os.environ[\"DB_PASSWORD\"]`.", "security") for s in secrets]


# ---------- Injection and unsafe input ----------
SQL_WORDS = re.compile(r"(?i)\b(select\s.+\sfrom|insert\s+into|update\s+\w+\s+set|delete\s+from|where\s)")


def _python(code: str) -> list[dict]:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []
    found = []

    def text_of(node):
        return ast.get_source_segment(code, node) or ""

    def built_string(node):
        """True if this builds a string out of pieces (f-string, +, %, .format)."""
        return (isinstance(node, ast.JoinedStr) and any(isinstance(v, ast.FormattedValue) for v in node.values)) or \
            (isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Mod))
             and any(isinstance(s, ast.Constant) and isinstance(s.value, str) for s in ast.walk(node))) or \
            (isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "format")

    built_queries = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and built_string(node.value) and SQL_WORDS.search(text_of(node.value)):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    built_queries[target.id] = node.lineno

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        line = node.lineno
        func = node.func
        name = getattr(func, "id", "") or getattr(func, "attr", "")
        full = text_of(func)
        if name in ("execute", "executemany", "executescript", "raw", "read_sql", "read_sql_query") and node.args:
            first = node.args[0]
            if built_string(first) or (isinstance(first, ast.Name) and first.id in built_queries):
                found.append(finding(line, "critical", "security",
                                     "SQL injection: the query is built by gluing text together, so someone can type "
                                     "SQL into the input and run their own commands on the database.",
                                     'Use parameters: `cursor.execute("SELECT * FROM users WHERE name = ?", (name,))`.', "security"))
        elif name in ("eval", "exec") and isinstance(func, ast.Name):
            found.append(finding(line, "critical", "security",
                                 f"`{name}()` runs any text as Python code. If that text comes from a user, they can run anything on the computer.",
                                 "Don't run text as code. For numbers use `int()`/`float()`; for data use `json.loads()` or `ast.literal_eval()`.", "security"))
        elif full in ("os.system", "os.popen") or (name in ("call", "run", "Popen", "check_output", "check_call")
                                                   and any(k.arg == "shell" and getattr(k.value, "value", False) is True for k in node.keywords)):
            dynamic = node.args and not isinstance(node.args[0], ast.Constant)
            found.append(finding(line, "critical" if dynamic else "warning", "security",
                                 "Command injection: this runs a shell command" + (" built from variables, so a user could add their own commands." if dynamic else "."),
                                 'Use `subprocess.run(["program", arg1, arg2])` with a list and without `shell=True`.', "security"))
        elif full in ("pickle.load", "pickle.loads", "marshal.loads", "shelve.open", "dill.loads"):
            found.append(finding(line, "warning", "security",
                                 "Loading pickled data can run hidden code if the data comes from someone else.",
                                 "Only load pickle files you created yourself; use JSON for data from users.", "security"))
        elif full == "yaml.load" and not any(k.arg == "Loader" and "Safe" in text_of(k.value) for k in node.keywords):
            found.append(finding(line, "warning", "security", "`yaml.load` without a safe loader can create any Python object.",
                                 "Use `yaml.safe_load(...)`.", "security"))
        elif any(k.arg == "verify" and getattr(k.value, "value", None) is False for k in node.keywords):
            found.append(finding(line, "warning", "security",
                                 "`verify=False` turns off the HTTPS certificate check, so someone in the middle can read or change the traffic.",
                                 "Remove `verify=False` (or point `verify` at your company's certificate file).", "security"))
        elif full in ("hashlib.md5", "hashlib.sha1"):
            found.append(finding(line, "warning", "security", f"`{full}` is broken for security; never use it for passwords or signatures.",
                                 "For passwords use `hashlib.pbkdf2_hmac`, bcrypt or argon2; otherwise `hashlib.sha256`.", "security"))
        elif full == "tempfile.mktemp":
            found.append(finding(line, "warning", "security", "`tempfile.mktemp` can let another program take the file first.",
                                 "Use `tempfile.NamedTemporaryFile()` or `tempfile.mkstemp()`.", "security"))
        elif name == "render_template_string" and node.args and not isinstance(node.args[0], ast.Constant):
            found.append(finding(line, "critical", "security", "The page template is built from a variable, so a user could inject template code.",
                                 "Use `render_template('page.html', value=value)` with a fixed template.", "security"))
        elif name == "run" and any(k.arg == "debug" and getattr(k.value, "value", None) is True for k in node.keywords):
            found.append(finding(line, "warning", "security", "`debug=True` shows a console that can run code to anyone who opens the site.",
                                 "Turn debug off outside your own computer.", "security"))
        elif full.startswith("random.") and re.search(r"(?i)token|password|secret|otp|key|salt", text_of(node) + code.split("\n")[line - 1]):
            found.append(finding(line, "warning", "security", "`random` is predictable, so it must not create passwords, tokens or codes.",
                                 "Use the `secrets` module, e.g. `secrets.token_urlsafe(16)`.", "security"))
    return found


def _c_like(code: str, language: str) -> list[dict]:
    found = []
    clean = blank_comments_and_strings(code, language).split("\n")
    for no, (raw, text) in enumerate(zip(code.split("\n"), clean), start=1):
        query_built = SQL_WORDS.search(raw) and (re.search(r"[\"']\s*\+|\+\s*[\"']", raw) or "${" in raw)
        if language == "javascript":
            if re.search(r"\beval\s*\(|\bnew\s+Function\s*\(", text):
                found.append(finding(no, "critical", "security", "`eval` / `new Function` runs text as code; user input here lets anyone run code.",
                                     "Don't run text as code; use `JSON.parse` for data.", "security"))
            if re.search(r"\.(innerHTML|outerHTML)\s*\+?=|\bdocument\.write\(|dangerouslySetInnerHTML|insertAdjacentHTML\(", text):
                found.append(finding(no, "warning", "security",
                                     "Cross-site scripting (XSS): putting text into the page as HTML lets a user inject scripts.",
                                     "Use `textContent` (or let your framework escape it), or clean the HTML with DOMPurify.", "security"))
            if query_built and re.search(r"\.(query|execute|raw)\s*\(|\bsql\b|query\s*=", raw, re.IGNORECASE):
                found.append(finding(no, "critical", "security", "SQL injection: the query is built by gluing text together.",
                                     "Use placeholders: `db.query('SELECT * FROM users WHERE id = ?', [id])`.", "security"))
            if re.search(r"\b(exec|execSync)\s*\(", text) and ("+" in text or "${" in raw):
                found.append(finding(no, "critical", "security", "Command injection: a shell command is built from variables.",
                                     "Use `execFile('program', [arg1, arg2])` instead of `exec` with a string.", "security"))
            if re.search(r"\blocalStorage\.setItem\(\s*['\"][^'\"]*(token|jwt|password|secret)", raw, re.IGNORECASE):
                found.append(finding(no, "warning", "security", "A token or password is kept in localStorage, where any script on the page can read it.",
                                     "Keep login tokens in secure, HttpOnly cookies.", "security"))
            if re.search(r"Math\.random\(\)", text) and re.search(r"(?i)token|password|secret|otp|key", raw):
                found.append(finding(no, "warning", "security", "`Math.random()` is predictable, so it must not create tokens or passwords.",
                                     "Use `crypto.randomUUID()` or `crypto.getRandomValues()`.", "security"))
            if re.search(r"\bsetTimeout\(\s*['\"]|\bsetInterval\(\s*['\"]", raw):
                found.append(finding(no, "warning", "security", "Passing a string to setTimeout/setInterval runs it like `eval`.",
                                     "Pass a function: `setTimeout(() => doWork(), 1000)`.", "security"))
            if re.search(r"\bcrypto\.createCipher\(|\bnew\s+Buffer\(", text):
                found.append(finding(no, "warning", "security", "This Node.js function is deprecated and unsafe.",
                                     "Use `crypto.createCipheriv(...)` / `Buffer.from(...)`.", "security"))
        else:  # Java
            if query_built and re.search(r"(execute(Query|Update)?|prepareStatement|createQuery|createNativeQuery)\s*\(|String\s+\w*(sql|query)\w*\s*=",
                                         raw, re.IGNORECASE):
                found.append(finding(no, "critical", "security", "SQL injection: the query is built by gluing text together.",
                                     'Use a PreparedStatement: `ps = conn.prepareStatement("SELECT * FROM emp WHERE id = ?"); ps.setInt(1, id);`.', "security"))
            if re.search(r"Runtime\.getRuntime\(\)\.exec\(|new\s+ProcessBuilder\(", text):
                dynamic = "+" in text
                found.append(finding(no, "critical" if dynamic else "warning", "security",
                                     "This runs an operating-system command" + (" built from variables (command injection)." if dynamic else "."),
                                     "Pass the program and each argument separately and check user input against an allow-list.", "security"))
            if re.search(r"\bnew\s+ObjectInputStream\(|\.readObject\(\)", text):
                found.append(finding(no, "warning", "security", "Reading Java objects from outside data can run hidden code (unsafe deserialization).",
                                     "Use JSON (e.g. Jackson without default typing) for data from users.", "security"))
            if re.search(r'getInstance\(\s*"(MD5|SHA-?1|DES|RC4)\b|"[^"]*/ECB/', raw, re.IGNORECASE):
                found.append(finding(no, "warning", "security", "This uses a broken or weak encryption/hash method.",
                                     'Use "SHA-256" for hashes and "AES/GCM/NoPadding" for encryption.', "security"))
            if re.search(r"\bnew\s+Random\(", text) and re.search(r"(?i)token|password|secret|otp|key|salt", code):
                found.append(finding(no, "warning", "security", "`java.util.Random` is predictable, so it must not create tokens or passwords.",
                                     "Use `java.security.SecureRandom`.", "security"))
            if re.search(r"enableDefaultTyping\(|activateDefaultTyping\(", text):
                found.append(finding(no, "warning", "security", "Jackson default typing lets outside JSON create any class (a known attack).",
                                     "Turn it off, or use a strict allow-list of classes.", "security"))
    return found


def _sql(code: str) -> list[dict]:
    found = []
    for line, text in sql_statements(code):
        raw_upper = " ".join(text.upper().split())
        if re.search(r"\b(EXEC(UTE)?\s*\(|EXECUTE\s+IMMEDIATE|SP_EXECUTESQL)", raw_upper) and re.search(r"\|\||\+|CONCAT", raw_upper):
            found.append(finding(line, "critical", "security", "SQL injection: dynamic SQL is built by gluing text together.",
                                 "Use bind variables / parameters (`EXECUTE IMMEDIATE ... USING`, `sp_executesql` with @params).", "security"))
        if "XP_CMDSHELL" in raw_upper:
            found.append(finding(line, "critical", "security", "`xp_cmdshell` lets SQL run operating-system commands.",
                                 "Keep xp_cmdshell turned off and do this outside the database.", "security"))
        if re.search(r"\bGRANT\s+ALL\b", raw_upper) or re.search(r"\bTO\s+PUBLIC\b", raw_upper):
            found.append(finding(line, "warning", "security", "This gives very wide permissions.",
                                 "Grant only the permissions needed, to a specific role or user.", "security"))
    return found


def injection_findings(code: str, language: str) -> list[dict]:
    if language == "python":
        return _python(code)
    if language in ("javascript", "java"):
        return _c_like(code, language)
    if language == "sql":
        return _sql(code)
    return []


# ---------- Risky or outdated libraries ----------
RISKY_LIBRARIES = {
    "python": {
        "pickle": "can run hidden code when loading data from others; use json for outside data",
        "marshal": "not safe for data from others; use json",
        "shelve": "built on pickle, not safe for data from others",
        "telnetlib": "removed in Python 3.13 and sends everything unencrypted; use SSH (paramiko)",
        "ftplib": "sends passwords unencrypted; use SFTP (paramiko) or FTPS (ftplib.FTP_TLS)",
        "cgi": "removed in Python 3.13; use a web framework such as Flask",
        "cgitb": "removed in Python 3.13",
        "imp": "removed in Python 3.12; use importlib",
        "distutils": "removed in Python 3.12; use setuptools",
        "asyncore": "removed in Python 3.12; use asyncio",
        "asynchat": "removed in Python 3.12; use asyncio",
        "smtpd": "removed in Python 3.12; use aiosmtpd",
        "Crypto": "PyCrypto is abandoned and has known security holes; use `cryptography` or PyCryptodome",
        "urllib2": "Python 2 only; use urllib.request or requests",
        "md5": "Python 2 only and insecure; use hashlib.sha256",
        "sha": "Python 2 only and insecure; use hashlib.sha256",
        "optparse": "deprecated; use argparse",
        "xml.etree.ElementTree": "can be attacked with crafted XML from others; use defusedxml",
        "xml.dom.minidom": "can be attacked with crafted XML from others; use defusedxml",
        "xml.sax": "can be attacked with crafted XML from others; use defusedxml",
    },
    "javascript": {
        "request": "deprecated since 2020 and no longer fixed; use fetch or axios",
        "node-uuid": "deprecated; use the uuid package or crypto.randomUUID()",
        "moment": "in maintenance mode; use date-fns, Luxon or Day.js",
        "querystring": "legacy; use URLSearchParams",
        "jade": "renamed to pug years ago; old versions have security holes",
        "event-stream": "a version was hijacked to steal crypto wallets; avoid it",
        "md5": "MD5 is broken for security",
        "sha1": "SHA-1 is broken for security",
        "crypto-js": "no longer maintained; use the built-in Web Crypto / node:crypto",
        "colors": "a version was sabotaged by its author; pin a known-good version or use chalk",
        "faker": "a version was sabotaged by its author; use @faker-js/faker",
    },
    "java": {
        "org.apache.log4j": "Log4j 1.x is end-of-life with known holes; use Log4j 2 (2.17.1 or newer) or SLF4J + Logback",
        "org.apache.commons.collections.": "Commons Collections 3.x is known for deserialization attacks; use version 4",
        "sun.misc.": "internal JDK code that can break or disappear; use the public Java API",
        "java.util.Vector": "old and slow; use ArrayList",
        "java.util.Hashtable": "old; use HashMap or ConcurrentHashMap",
        "java.util.Stack": "old; use ArrayDeque",
        "java.util.Date": "old and error-prone; use java.time (LocalDate, Instant)",
        "java.text.SimpleDateFormat": "not thread-safe; use java.time.format.DateTimeFormatter",
        "java.applet": "removed from modern Java",
    },
}


def library_findings(code: str, language: str) -> list[dict]:
    risky = RISKY_LIBRARIES.get(language)
    if not risky:
        return []
    found, seen = [], set()
    for no, raw in enumerate(code.split("\n"), start=1):
        names = []
        if language == "python":
            m = re.match(r"\s*(?:from\s+([\w.]+)\s+import|import\s+([\w., ]+))", raw)
            if m:
                names = [m.group(1)] if m.group(1) else [n.strip().split(" as ")[0] for n in m.group(2).split(",")]
        elif language == "javascript":
            names = re.findall(r"""(?:require\(\s*|from\s+|import\s+)['"]([^'"]+)['"]""", raw)
        else:
            m = re.match(r"\s*import\s+(?:static\s+)?([\w.*]+)\s*;", raw)
            names = [m.group(1)] if m else []
        for name in names:
            for library, why in risky.items():
                matches = name == library or name.startswith(library if library.endswith(".") else library + ".") \
                    or (language == "java" and name.startswith(library))
                if language == "javascript":
                    matches = name == library or name.startswith(library + "/")
                if matches and library not in seen:
                    seen.add(library)
                    found.append(finding(no, "warning" if any(w in why for w in ("hole", "attack", "hijack", "sabotag", "hidden code", "unencrypted", "insecure", "broken"))
                                         else "suggestion", "security",
                                         f"`{name}` is a risky or outdated library: {why.split(';')[0]}.",
                                         (why.split("; ", 1)[1][0].upper() + why.split("; ", 1)[1][1:] + ".") if "; " in why else "Replace it with a maintained alternative.",
                                         "security"))
    return found


# ---------- Everything ----------
def scan(code: str, language: str) -> dict:
    """The full security scan: {"secrets": [...], "findings": [...]} (secrets come first)."""
    secrets = find_secrets(code)
    return {"secrets": secrets,
            "findings": secret_findings(secrets) + injection_findings(code, language) + library_findings(code, language)}


def security_findings(code: str, language: str) -> list[dict]:
    return scan(code, language)["findings"]
