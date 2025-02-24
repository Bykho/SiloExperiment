import os
import re
import requests
from flask import Blueprint, jsonify, request, Response, stream_with_context
import json
from openai import OpenAI
import io
import mimetypes
import requests
import time
from tenacity import retry, stop_after_attempt, wait_exponential
from typing_extensions import override
from openai import AssistantEventHandler

routes = Blueprint("routes", __name__)

# Environment variables
GITHUB_API_KEY = os.getenv("GITHUB_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
VECTOR_STORE_ID = os.getenv("VECTOR_STORE_ID")  # e.g. vs_ANGoJfG1WLHRoVM9x46J8dH4
ASSISTANT_ID = os.getenv("ASSISTANT_ID")        # e.g. asst_ICqgIQQ0DZGNCRI48Ic77Oww


# ======== SECURE SSL CONFIG ======== #
SESSION = requests.Session()
SESSION.verify = True  # Use system CA bundle automatically
SESSION.timeout = (3.05, 27)  # Connect + read timeouts

# ======== RETRY LOGIC ======== #
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def openai_upload_with_retry(client, content, filename, mimetype):
    return client.files.create(
        file=(filename, io.BytesIO(content), mimetype),
        purpose="assistants"
    )




def register_routes(app):
    """Register this blueprint with the Flask app."""
    app.register_blueprint(routes)

@routes.route("/api/keys", methods=["GET"])
def check_keys():
    """
    Check if GitHub API key, OpenAI API key, Vector Store ID and Assistant ID exist.
    Returns a JSON object with boolean values indicating whether each key/ID exists.
    """
    return jsonify({
        "github_api_key": bool(GITHUB_API_KEY),
        "openai_api_key": bool(OPENAI_API_KEY),
        "vector_store_id": bool(VECTOR_STORE_ID),
        "assistant_id": bool(ASSISTANT_ID),
    })

@routes.route("/api/repos", methods=["GET"])
def get_github_repos():
    """
    Return a list of GitHub repositories for a specified user.
    """
    if not GITHUB_API_KEY:
        return jsonify({"error": "GitHub API key not found"}), 403

    headers = {"Authorization": f"token {GITHUB_API_KEY}"}
    response = requests.get("https://api.github.com/users/Bykho/repos", headers=headers)
    if response.status_code != 200:
        return jsonify({"error": "Failed to fetch repositories"}), response.status_code

    repos = [
        {"id": repo["id"], "name": repo["name"], "url": repo["html_url"]}
        for repo in response.json()
    ]
    return jsonify({"repositories": repos})

###############################################################################
# Exclusion Patterns
###############################################################################

# Directories we do NOT want to traverse
excluded_dir_patterns = [
    re.compile(r"node_modules", re.IGNORECASE),
    re.compile(r"virtualenvs", re.IGNORECASE),
    re.compile(r"dist", re.IGNORECASE),
    re.compile(r"build", re.IGNORECASE),
    re.compile(r"target", re.IGNORECASE),
    re.compile(r"bin", re.IGNORECASE),
    re.compile(r"public", re.IGNORECASE),
    re.compile(r"static", re.IGNORECASE),
    re.compile(r"tests?", re.IGNORECASE),
    re.compile(r"docs?", re.IGNORECASE),
    re.compile(r"examples?", re.IGNORECASE),
    re.compile(r"myenv?", re.IGNORECASE)
]

# Files we do NOT want to upload, no matter the extension
excluded_file_patterns = [
    re.compile(r"\.env$", re.IGNORECASE),
    re.compile(r"\.prettierrc$", re.IGNORECASE),
    re.compile(r"\.eslintrc$", re.IGNORECASE),
    re.compile(r"tsconfig\.json$", re.IGNORECASE),
    re.compile(r"package\.json$", re.IGNORECASE),
    re.compile(r"yarn\.lock$", re.IGNORECASE),
    re.compile(r"\.gitignore$", re.IGNORECASE),
    re.compile(r"LICENSE$", re.IGNORECASE),
    re.compile(r"CHANGELOG\.md$", re.IGNORECASE),
    re.compile(r"CONTRIBUTING\.md$", re.IGNORECASE),
    re.compile(r"\.ds_store$", re.IGNORECASE),
    re.compile(r"\.log$", re.IGNORECASE),
    re.compile(r"\.min\.js$", re.IGNORECASE),
    re.compile(r"\.(png|jpg|jpeg|gif|svg)$", re.IGNORECASE),
    re.compile(r"\.(ttf|woff|woff2|eot)$", re.IGNORECASE),
    re.compile(r"\.(json|yaml|yml|xml)$", re.IGNORECASE),
    re.compile(r"\.venv2$", re.IGNORECASE),
    re.compile(r"\.myenv$", re.IGNORECASE),

]

# Allowed text/code extensions for the OpenAI Vector Store Beta
allowed_extensions = (
    ".txt", ".md", ".markdown", ".py", ".js", ".java",
    ".csv", ".ts", ".c", ".cpp", ".css", ".html",
    ".sh", ".php", ".tex", ".ps1"
)

def skip_directory(dir_path: str) -> bool:
    """
    Return True if `dir_path` should be excluded (node_modules, build, etc.).
    """
    lp = dir_path.lower()
    for pattern in excluded_dir_patterns:
        if pattern.search(lp):
            print(f"[DEBUG] Skipping directory: {dir_path}")
            return True
    return False

def skip_file(file_path: str) -> bool:
    """
    Return True if `file_path` should be excluded or does not have an allowed extension.
    """
    lp = file_path.lower()

    # Check direct file exclusion patterns first
    for pattern in excluded_file_patterns:
        if pattern.search(lp):
            print(f"[DEBUG] Skipping file (excluded pattern): {file_path}")
            return True

    # Then check allowed extensions
    if not lp.endswith(allowed_extensions):
        print(f"[DEBUG] Skipping file (extension not allowed): {file_path}")
        return True

    return False

###############################################################################
# Recursively fetch files from GitHub
###############################################################################
def fetch_repo_files_recursively(owner: str, repo: str, path: str, headers: dict) -> list:
    """
    Recursively traverse a GitHub repo at `path`, skipping excluded directories,
    returning a list of valid file objects for upload.
    """
    file_list = []
    api_url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"

    while api_url:
        resp = requests.get(api_url, headers=headers)
        if resp.status_code != 200:
            print(f"[DEBUG] Failed to fetch {api_url}, status code: {resp.status_code}")
            break

        items = resp.json()
        if not isinstance(items, list):
            print(f"[DEBUG] Unexpected GitHub API response at {api_url}: {items}")
            break

        print(f"[DEBUG] Fetched {len(items)} items from {api_url}.")

        for item in items:
            name = item.get("name", "")
            item_path = item.get("path", "")
            item_type = item.get("type", "")

            if item_type == "dir":
                if not skip_directory(item_path):
                    file_list.extend(fetch_repo_files_recursively(owner, repo, item_path, headers))
            elif item_type == "file":
                if not skip_file(item_path):
                    print(f"[DEBUG] -> Adding file to final upload list: {item_path}")
                    file_list.append(item)
            else:
                print(f"[DEBUG] Skipping unknown item type: {name}, type={item_type}")

        api_url = resp.links.get("next", {}).get("url")

    return file_list

mime_map = {
    ".cpp": "text/x-c++",
    ".py": "text/x-python",
    ".js": "text/javascript",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".h": "text/x-c-header",
    ".hpp": "text/x-c++hdr",
    ".c": "text/x-c",
    ".html": "text/html",
    ".css": "text/css",
    ".java": "text/x-java-source",
    ".sh": "text/x-shellscript",
    ".ps1": "application/x-powershell",
    ".ts": "text/x-typescript",
    ".csv": "text/csv",
    ".php": "text/x-php",
    ".tex": "text/x-tex"
}

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def openai_upload_with_retry(client, content, filename, mimetype):
    return client.files.create(
        file=(filename, io.BytesIO(content), mimetype),
        purpose="assistants"
    )

@routes.route("/api/upload_to_vs", methods=["POST"])
def upload_to_vs():
    if not GITHUB_API_KEY or not OPENAI_API_KEY:
        return jsonify({"error": "Missing API keys"}), 403

    data = request.get_json()
    repo = data.get("repo")
    if not repo or "name" not in repo:
        return jsonify({"error": "Invalid repository data"}), 400

    repo_name = repo["name"]
    print(f"[DEBUG] Starting upload_to_vs for repo: {repo_name}")

    headers = {"Authorization": f"token {GITHUB_API_KEY}"}
    github_files = fetch_repo_files_recursively("Bykho", repo_name, "", headers)

    print(f"[DEBUG] Final list of files to upload: {[f.get('path') for f in github_files]}")

    client = OpenAI(api_key=OPENAI_API_KEY)

    attached_file_ids = []
    errors = []

    for file_info in github_files:
        file_path = file_info.get("path", "")
        download_url = file_info.get("download_url", "")
        print(f"[DEBUG] Attempting to upload file: {file_path}")

        if not download_url:
            print(f"[DEBUG] -> No download_url found for file: {file_path}")
            continue

        try:
            file_content_resp = SESSION.get(download_url, timeout=10)
            
            if file_content_resp.status_code != 200:
                raise requests.HTTPError(f"HTTP {file_content_resp.status_code}")

            content = file_content_resp.content

            if len(content) == 0:
                print(f"[DEBUG] -> Skipping '{file_path}' because it's empty (0 bytes).")
                continue

            try:
                content.decode("utf-8")
            except UnicodeDecodeError:
                print(f"[DEBUG] -> Skipping non-UTF-8 file: {file_path}")
                continue

            filename = os.path.basename(file_path)
            extension = os.path.splitext(filename)[1].lower()
            mimetype = mime_map.get(extension, "text/plain")

            uploaded_file = openai_upload_with_retry(client, content, filename, mimetype)
            print(f"[DEBUG] -> Uploaded file: {file_path}, file_id={uploaded_file.id}")

            try:
                vs_file = client.beta.vector_stores.files.create(
                    vector_store_id=VECTOR_STORE_ID,
                    file_id=uploaded_file.id
                )
                attached_file_ids.append(uploaded_file.id)
                print(f"[DEBUG] -> Attached file '{file_path}' to Vector Store: {vs_file}")
            except Exception as attach_err:
                msg = f"Failed to attach file '{file_path}' (file_id={uploaded_file.id}) to Vector Store: {attach_err}"
                print(f"[DEBUG] -> {msg}")
                errors.append(msg)

        except requests.exceptions.SSLError as e:
            errors.append(f"SSL failure for {file_path}: {str(e)}")
        except requests.exceptions.ConnectionError as e:
            errors.append(f"Connection failed for {file_path}: {str(e)}")
        except requests.exceptions.Timeout as e:
            errors.append(f"Timeout occurred for {file_path}: {str(e)}")
        except Exception as e:
            errors.append(f"Unexpected error with {file_path}: {str(e)}")

    if not attached_file_ids and not errors:
        return jsonify({"message": "No supported files uploaded."})
    else:
        return jsonify({
            "message": "Finished attempting to upload & attach files.",
            "attached_file_ids": attached_file_ids,
            "errors": errors
        })
    



############# new additions ##############








class OutlineEventHandler(AssistantEventHandler):    
    def __init__(self):
        super().__init__()
        self.queue = []
    
    @override
    def on_text_created(self, text) -> None:
        # This adds a formatted message to the queue
        self.queue.append(f"data: {json.dumps({'content': '\\n'})}\n\n")
          
    @override
    def on_text_delta(self, delta, snapshot):
        if delta.value:
            print(f"[DEBUG] Delta value: {delta.value}")
            # This adds a formatted message to the queue
            self.queue.append(f"data: {json.dumps({'content': delta.value})}\n\n")

@routes.route("/api/generate_outline", methods=["POST"])
def generate_outline():
    if not OPENAI_API_KEY or not ASSISTANT_ID:
        return jsonify({"error": "Missing API keys or IDs"}), 403

    data = request.get_json()
    repo = data.get("repo")
    if not repo or "name" not in repo:
        return jsonify({"error": "Invalid repository data"}), 400

    def event_stream():
        try:
            client = OpenAI(api_key=OPENAI_API_KEY)
            thread = client.beta.threads.create()
            print(f"[DEBUG] Created thread: {thread.id}")
            
            client.beta.threads.messages.create(
                thread_id=thread.id,
                role="user",
                content=f"Generate an outline for the repository: {repo['name']} that is in the vector store attached to you"
            )

            handler = OutlineEventHandler()
            print("[DEBUG] Handler created")
            
            # Create a flag to track when the stream is done
            stream_done = False
            
            # Start the streaming in the background
            def process_stream():
                nonlocal stream_done
                try:
                    with client.beta.threads.runs.stream(
                        thread_id=thread.id,
                        assistant_id=ASSISTANT_ID,
                        instructions="""
                        Generate a concise, well-structured outline for an engineering portfolio entry based on the repository.
                        Format the outline as follows:
                        1. Start with a clear title and brief overview (2-3 sentences)
                        2. Organize into 5-7 main sections with clear headings (use ### for main headings)
                        3. Use bullet points for subsections (use - for bullets)
                        4. Include specific technical details relevant to the repository
                        5. Add proper spacing between sections using a blank line
                        6. End with potential discussion points about challenges and solutions

                        Focus on the core technologies, architecture, and unique features of the project.
                        Keep descriptions brief but informative - aim for clarity over comprehensiveness.
                        """,  # Added comma here
                        event_handler=handler
                    ) as stream:
                        print("[DEBUG] Stream started")
                        stream.until_done()
                        print("[DEBUG] Stream completed")
                except Exception as e:
                    print(f"[DEBUG] Error in stream processing: {str(e)}")
                    handler.queue.append(f"data: {json.dumps({'error': str(e)})}\n\n")
                finally:
                    stream_done = True
            
            # Start the streaming thread
            import threading
            stream_thread = threading.Thread(target=process_stream)
            stream_thread.start()
            
            # Yield events as they become available in the queue
            while True:
                if handler.queue:
                    yield handler.queue.pop(0)
                elif stream_done:
                    break
                else:
                    # Small sleep to avoid busy waiting
                    time.sleep(0.1)
                
        except Exception as e:
            print(f"[DEBUG] Error in event stream setup: {str(e)}")
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return Response(
        stream_with_context(event_stream()), 
        content_type='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'Content-Type': 'text/event-stream',
            'Connection': 'keep-alive',
            'Access-Control-Allow-Origin': '*'
        }
    )

