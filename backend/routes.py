import os
import re
import requests
from flask import Blueprint, jsonify, request, Response, stream_with_context
import json
from openai import OpenAI
import io
import mimetypes
import time
from tenacity import retry, stop_after_attempt, wait_exponential
from typing_extensions import override
from openai import AssistantEventHandler

routes = Blueprint("routes", __name__)
def register_routes(app):
    """Register this blueprint with the Flask app."""
    app.register_blueprint(routes)

# Environment variables (for pre-built mode)
GITHUB_API_KEY = os.getenv("GITHUB_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
PREBUILT_VECTOR_STORE_ID = os.getenv("VECTOR_STORE_ID")  # e.g. vs_ANGoJfG1WLHRoVM9x46J8dH4
PREBUILT_ASSISTANT_ID = os.getenv("ASSISTANT_ID")        # e.g. asst_ICqgIQQ0DZGNCRI48Ic77Oww

###############################################################################
# Helper Functions & Constants
###############################################################################

# Maximum allowed file size in bytes (e.g., 1MB)
MAX_FILE_SIZE = 1_000_000

# Excluded directory patterns
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
    re.compile(r"myenv?", re.IGNORECASE),
    re.compile(r".venv", re.IGNORECASE)
]

# Excluded file patterns
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

# Allowed file extensions
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

# --- New helper function for virtual environment and dependency detection ---
def is_venv_or_dependency_file(file_path: str) -> bool:
    """
    Check if the file path indicates that the file belongs to a virtual environment
    or a dependency directory. Uses path component checking to avoid false positives.
    """
    # Markers for virtual environments
    venv_markers = [
        "pyvenv.cfg",
        "bin/activate",
        "scripts/activate",
        "lib/site-packages",
        "include/site",
        "__pycache__",
        "lib64",
        ".python"
    ]
    # Markers for common dependency directories
    dependency_markers = [
        "node_modules",
        "bower_components",
        "vendor",
        "packages",
        ".git",
        ".svn",
        ".venv",
        "venv",
        "env",
        ".env"
    ]
    lp = file_path.lower()
    # Check virtual environment markers using path component checking
    for marker in venv_markers:
        if f"/{marker}/" in lp or lp.endswith(f"/{marker}") or lp.startswith(f"{marker}/"):
            print(f"[DEBUG] Skipping file (virtual environment marker '{marker}'): {file_path}")
            return True
    # Check dependency directory markers
    for marker in dependency_markers:
        if f"/{marker}/" in lp or lp.startswith(f"{marker}/"):
            print(f"[DEBUG] Skipping file (dependency marker '{marker}'): {file_path}")
            return True
    # Skip common compiled or binary files
    compiled_extensions = [
        ".pyc", ".pyo", ".so", ".dll", ".class", ".o", ".obj",
        ".jar", ".war", ".ear", ".exe", ".bin", ".out"
    ]
    for ext in compiled_extensions:
        if lp.endswith(ext):
            print(f"[DEBUG] Skipping compiled/binary file: {file_path}")
            return True
    return False

def skip_file(file_info: dict) -> bool:
    """
    Return True if the file (represented by file_info) should be excluded.
    Checks file size, file exclusion patterns, virtual environment/dependency markers,
    and allowed file extensions.
    """
    file_path = file_info.get("path", "")
    file_size = file_info.get("size", 0)
    lp = file_path.lower()

    # Skip oversized files
    if file_size > MAX_FILE_SIZE:
        print(f"[DEBUG] Skipping oversized file: {file_path} ({file_size} bytes)")
        return True

    # Check hardcoded exclusion patterns
    for pattern in excluded_file_patterns:
        if pattern.search(lp):
            print(f"[DEBUG] Skipping file (excluded pattern): {file_path}")
            return True

    # Check for virtual environment/dependency markers
    if is_venv_or_dependency_file(file_path):
        return True

    # Check for allowed file extensions
    if not lp.endswith(allowed_extensions):
        print(f"[DEBUG] Skipping file (extension not allowed): {file_path}")
        return True

    return False

###############################################################################
# Recursively fetch files from GitHub with parallel processing
###############################################################################
def fetch_repo_files_recursively(owner: str, repo: str, path: str, headers: dict) -> list:
    """
    Recursively traverse a GitHub repo at `path`, skipping excluded directories and files,
    and return a list of valid file objects.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    file_list = []
    
    def process_directory(dir_path, depth=0, max_depth=8):
        if depth > max_depth:
            print(f"[DEBUG] Reached maximum depth at {dir_path}")
            return []
        local_files = []
        api_url = f"https://api.github.com/repos/{owner}/{repo}/contents/{dir_path}"
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
            
            dirs_to_process = []
            for item in items:
                item_type = item.get("type", "")
                if item_type == "dir":
                    if not skip_directory(item.get("path", "")):
                        dirs_to_process.append(item.get("path", ""))
                elif item_type == "file":
                    if not skip_file(item):
                        print(f"[DEBUG] -> Adding file to final upload list: {item.get('path', '')}")
                        local_files.append(item)
                else:
                    print(f"[DEBUG] Skipping unknown item type: {item.get('name', '')}, type={item_type}")
            
            if dirs_to_process:
                with ThreadPoolExecutor(max_workers=min(10, len(dirs_to_process))) as executor:
                    future_to_dir = {executor.submit(process_directory, d, depth+1, max_depth): d for d in dirs_to_process}
                    for future in as_completed(future_to_dir):
                        local_files.extend(future.result())
            
            api_url = resp.links.get("next", {}).get("url")
        return local_files
    
    return process_directory(path)

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

SESSION = requests.Session()
SESSION.verify = True
SESSION.timeout = (3.05, 27)

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def openai_upload_with_retry(client, content, filename, mimetype):
    return client.files.create(
        file=(filename, io.BytesIO(content), mimetype),
        purpose="assistants"
    )

def find_assistant_by_name(client, name):
    """Find an assistant by name from the list of all assistants."""
    try:
        assistants = client.beta.assistants.list(limit=100)
        for assistant in assistants.data:
            if assistant.name == name:
                return assistant
    except Exception as e:
        print(f"[DEBUG] Error listing assistants: {str(e)}")
    return None

def create_dynamic_assistant_helper(repo):
    """
    Helper to create a new vector store and dynamic assistant for the repository.
    Returns a dict with the new vector store and assistant IDs.
    """
    if not GITHUB_API_KEY or not OPENAI_API_KEY:
        raise Exception("Missing API keys")
        
    repo_name = repo["name"]
    print(f"[DEBUG] Starting dynamic upload for repo: {repo_name}")
    client = OpenAI(api_key=OPENAI_API_KEY)
    
    try:
        new_vector_store = client.beta.vector_stores.create(
            name=f"vs_{repo_name}",
            expires_after={"anchor": "last_active_at", "days": 1}
        )
        dynamic_vector_store_id = new_vector_store.id
        print(f"[DEBUG] Created dynamic vector store with id: {dynamic_vector_store_id}")
    except Exception as e:
        raise Exception(f"Error creating dynamic vector store: {str(e)}")
        
    headers = {"Authorization": f"token {GITHUB_API_KEY}"}
    github_files = fetch_repo_files_recursively("Bykho", repo_name, "", headers)
    print(f"[DEBUG] Files to upload: {[f.get('path') for f in github_files]}")
    attached_file_ids = []
    errors = []

    from concurrent.futures import ThreadPoolExecutor, as_completed
    
    def process_file(file_info):
        file_path = file_info.get("path", "")
        download_url = file_info.get("download_url", "")
        print(f"[DEBUG] Processing file: {file_path}")
        if not download_url:
            return None, None
        try:
            file_content_resp = SESSION.get(download_url, timeout=10)
            if file_content_resp.status_code != 200:
                raise requests.HTTPError(f"HTTP {file_content_resp.status_code}")
            content = file_content_resp.content
            if len(content) == 0:
                print(f"[DEBUG] Skipping empty file: {file_path}")
                return None, None
            try:
                content.decode("utf-8")
            except UnicodeDecodeError:
                print(f"[DEBUG] Skipping non-UTF-8 file: {file_path}")
                return None, None
            filename = os.path.basename(file_path)
            extension = os.path.splitext(filename)[1].lower()
            mimetype = mime_map.get(extension, "text/plain")
            uploaded_file = openai_upload_with_retry(client, content, filename, mimetype)
            print(f"[DEBUG] Uploaded file: {file_path}, id: {uploaded_file.id}")
            vs_file = client.beta.vector_stores.files.create(
                vector_store_id=dynamic_vector_store_id,
                file_id=uploaded_file.id
            )
            return uploaded_file.id, None
        except Exception as e:
            error_msg = f"Error processing {file_path}: {str(e)}"
            print(f"[DEBUG] {error_msg}")
            return None, error_msg
    
    max_workers = min(20, len(github_files))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_file = {executor.submit(process_file, file_info): file_info for file_info in github_files}
        for future in as_completed(future_to_file):
            file_id, error = future.result()
            if file_id:
                attached_file_ids.append(file_id)
            if error:
                errors.append(error)
    try:
        new_assistant = client.beta.assistants.create(
            name=repo_name,
            instructions="You are an assistant that helps analyze code repositories and generate project outlines.",
            model="gpt-4-turbo",
            tools=[{"type": "file_search"}],
            tool_resources={"file_search": {"vector_store_ids": [dynamic_vector_store_id]}},
        )
        dynamic_assistant_id = new_assistant.id
        print(f"[DEBUG] Created dynamic assistant with id: {dynamic_assistant_id}")
    except Exception as e:
        raise Exception(f"Error creating dynamic assistant: {str(e)}")
    
    return {
        "dynamic_vector_store_id": dynamic_vector_store_id,
        "dynamic_assistant_id": dynamic_assistant_id,
        "attached_file_ids": attached_file_ids,
        "errors": errors
    }

###############################################################################
# Pre-built Endpoints
###############################################################################
@routes.route("/api/keys", methods=["GET"])
def check_keys():
    return jsonify({
        "github_api_key": bool(GITHUB_API_KEY),
        "openai_api_key": bool(OPENAI_API_KEY),
        "vector_store_id": bool(PREBUILT_VECTOR_STORE_ID),
        "assistant_id": bool(PREBUILT_ASSISTANT_ID),
    })

@routes.route("/api/repos", methods=["GET"])
def get_github_repos():
    if not GITHUB_API_KEY:
        return jsonify({"error": "GitHub API key not found"}), 403
    headers = {"Authorization": f"token {GITHUB_API_KEY}"}
    response = requests.get("https://api.github.com/users/Bykho/repos", headers=headers)
    if response.status_code != 200:
        return jsonify({"error": "Failed to fetch repositories"}), response.status_code
    repos = [{"id": repo["id"], "name": repo["name"], "url": repo["html_url"]} for repo in response.json()]
    return jsonify({"repositories": repos})

############# Layer 1 ##############
class OutlineEventHandler(AssistantEventHandler):    
    def __init__(self):
        super().__init__()
        self.queue = []
    
    @override
    def on_text_created(self, text) -> None:
        self.queue.append(f"data: {json.dumps({'content': '\\n'})}\n\n")
          
    @override
    def on_text_delta(self, delta, snapshot):
        if delta.value:
            self.queue.append(f"data: {json.dumps({'content': delta.value})}\n\n")


###############################################################################
# Dynamic Endpoints
###############################################################################
@routes.route("/api/dynamic_upload_to_vs", methods=["POST"])
def dynamic_upload_to_vs():
    """
    Dynamic Build Entry endpoint:
    - Creates a new vector store specific to the repository.
    - Uploads the repository's files into that new vector store.
    - Creates a new assistant linked to the new vector store.
    The assistant is named after the repository so that later lookups are simple.
    """
    if not GITHUB_API_KEY or not OPENAI_API_KEY:
        return jsonify({"error": "Missing API keys"}), 403
    data = request.get_json()
    repo = data.get("repo")
    if not repo or "name" not in repo:
        return jsonify({"error": "Invalid repository data"}), 400
    
    try:
        result = create_dynamic_assistant_helper(repo)
        return jsonify({
            "message": "Dynamic upload complete.",
            "dynamic_vector_store_id": result["dynamic_vector_store_id"],
            "dynamic_assistant_id": result["dynamic_assistant_id"],
            "attached_file_ids": result["attached_file_ids"],
            "errors": result["errors"]
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@routes.route("/api/dynamic_generate_outline", methods=["POST"])
def dynamic_generate_outline():
    """
    Dynamic Generate Outline endpoint:
    - Looks up the dynamic assistant by repository name.
    - If not found, automatically creates a new vector store and assistant.
    - Streams an outline generated by the dynamic assistant.
    """
    if not OPENAI_API_KEY:
        return jsonify({"error": "Missing API keys"}), 403
    data = request.get_json()
    repo = data.get("repo")
    if not repo or "name" not in repo:
        return jsonify({"error": "Invalid repository data"}), 400
    repo_name = repo["name"]
    print(f"[DEBUG] Starting dynamic outline generation for repo: {repo_name}")
    client = OpenAI(api_key=OPENAI_API_KEY)
    dynamic_assistant = find_assistant_by_name(client, repo_name)
    if not dynamic_assistant:
        print(f"[DEBUG] Dynamic assistant not found for repo: {repo_name}. Creating one...")
        try:
            create_dynamic_assistant_helper(repo)
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        dynamic_assistant = find_assistant_by_name(client, repo_name)
        if not dynamic_assistant:
            return jsonify({"error": "Failed to create dynamic assistant."}), 500
    dynamic_assistant_id = dynamic_assistant.id
    print(f"[DEBUG] Retrieved dynamic assistant with id: {dynamic_assistant_id}")

    def event_stream():
        try:
            thread = client.beta.threads.create()
            print(f"[DEBUG] Created thread: {thread.id}")
            client.beta.threads.messages.create(
                thread_id=thread.id,
                role="user",
                content=f"Generate an outline for the repository: {repo_name} that is in the vector store attached to you"
            )
            handler = OutlineEventHandler()
            print("[DEBUG] Handler created for dynamic outline")
            stream_done = False
            def process_stream():
                nonlocal stream_done
                try:
                    with client.beta.threads.runs.stream(
                        thread_id=thread.id,
                        assistant_id=dynamic_assistant_id,
                        instructions="""
                        Generate a concise, well-structured outline for an engineering portfolio entry based solely on the repository's code.
                        The repository's code is in the dynamic vector store attached to you.
                        Follow this exact format:
                        1. Provide 5 sections, each starting with a header: ---SECTION_TITLE: [Title]
                        2. Under each header, list markdown bullet points.
                        3. One of the sections should have the title "TL:DR" . in this section, give a super concise description of this project that explainswhy I (the creator of this project) am a fantastic engineer. no bullet points in this section.

                        Do not include any extra formatting.
                        """,
                        event_handler=handler
                    ) as stream:
                        print("[DEBUG] Dynamic stream started")
                        stream.until_done()
                        print("[DEBUG] Dynamic stream completed")
                except Exception as e:
                    handler.queue.append(f"data: {json.dumps({'error': str(e)})}\n\n")
                finally:
                    stream_done = True
            import threading
            stream_thread = threading.Thread(target=process_stream)
            stream_thread.start()
            while True:
                if handler.queue:
                    yield handler.queue.pop(0)
                elif stream_done:
                    break
                else:
                    time.sleep(0.1)
        except Exception as e:
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

@routes.route("/api/dynamic_expand_topic", methods=["POST"])
def dynamic_expand_topic():
    """
    Dynamic Expand Topic endpoint:
    - Uses the dynamic assistant (looked up by repository name) to expand on a given topic.
    - Streams the expanded content back to the client.
    """
    if not OPENAI_API_KEY:
        return jsonify({"error": "Missing API keys"}), 403
    
    # Log request data
    print(f"[DEBUG] Received request to /api/dynamic_expand_topic")
    
    try:
        data = request.get_json()
        print(f"[DEBUG] Request data: {data}")
        
        topic = data.get("topic")
        repo = data.get("repo")
        
        # Validate request data with detailed logging
        if not topic:
            print(f"[ERROR] Missing topic in request data")
            return jsonify({"error": "Missing topic in request data"}), 400
        if not repo:
            print(f"[ERROR] Missing repo in request data")
            return jsonify({"error": "Missing repo in request data"}), 400
        if "name" not in repo:
            print(f"[ERROR] Missing repo name in request data. Repo data: {repo}")
            return jsonify({"error": "Missing repo name in request data"}), 400
        
        repo_name = repo["name"]
        print(f"[DEBUG] Starting dynamic expand topic for repo: {repo_name} and topic: {topic}")
        
        client = OpenAI(api_key=OPENAI_API_KEY)
        try:
            dynamic_assistant = find_assistant_by_name(client, repo_name)
            if not dynamic_assistant:
                print(f"[ERROR] Dynamic assistant not found for repo: {repo_name}")
                return jsonify({"error": "Dynamic assistant not found. Please build the entry first."}), 404
            
            dynamic_assistant_id = dynamic_assistant.id
            print(f"[DEBUG] Retrieved dynamic assistant with id: {dynamic_assistant_id}")
        except Exception as e:
            print(f"[ERROR] Failed to retrieve dynamic assistant: {str(e)}")
            return jsonify({"error": "Failed to retrieve dynamic assistant.", "details": str(e)}), 500
        
        def event_stream():
            try:
                thread = client.beta.threads.create()
                print(f"[DEBUG] Created thread: {thread.id}")
                
                # Log message creation
                print(f"[DEBUG] Creating message with topic: {topic}")
                client.beta.threads.messages.create(
                    thread_id=thread.id,
                    role="user",
                    content=f"Expand on the following topic: {topic}"
                )
                print(f"[DEBUG] Message created successfully")
                
                handler = OutlineEventHandler()
                stream_done = False
                
                def process_stream():
                    nonlocal stream_done
                    try:
                        print(f"[DEBUG] Starting stream with thread_id: {thread.id}, assistant_id: {dynamic_assistant_id}")
                        with client.beta.threads.runs.stream(
                            thread_id=thread.id,
                            assistant_id=dynamic_assistant_id,
                            instructions="""
                            Expand on the given subtopic as part of a larger project.
                            Provide detailed, well-structured content with technical details and clear explanations.
                            Do not use bullet points.
                            Emphasize the connection between this subtopic and the overall project.
                            Keep it short.
                            """,
                            event_handler=handler
                        ) as stream:
                            print(f"[DEBUG] Stream created successfully, waiting for completion")
                            stream.until_done()
                            print(f"[DEBUG] Stream completed successfully")
                    except Exception as e:
                        print(f"[ERROR] Error in stream processing: {str(e)}")
                        handler.queue.append(f"data: {json.dumps({'error': str(e)})}\n\n")
                    finally:
                        stream_done = True
                        print(f"[DEBUG] Stream processing finished")
                
                import threading
                stream_thread = threading.Thread(target=process_stream)
                stream_thread.start()
                print(f"[DEBUG] Stream thread started")
                
                while True:
                    if handler.queue:
                        data = handler.queue.pop(0)
                        print(f"[DEBUG] Yielding data: {data[:100]}...")  # Log first 100 chars
                        yield data
                    elif stream_done:
                        print(f"[DEBUG] Stream done, breaking loop")
                        break
                    else:
                        time.sleep(0.1)
            except Exception as e:
                error_msg = f"data: {json.dumps({'error': str(e)})}\n\n"
                print(f"[ERROR] Exception in event_stream: {str(e)}")
                yield error_msg
        
        print(f"[DEBUG] Returning streaming response")
        return Response(
            stream_with_context(event_stream()),
            content_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Content-Type": "text/event-stream",
                "Connection": "keep-alive",
                "Access-Control-Allow-Origin": "*"
            }
        )
    except Exception as e:
        print(f"[ERROR] Unhandled exception in dynamic_expand_topic: {str(e)}")
        return jsonify({"error": f"Server error: {str(e)}"}), 500
