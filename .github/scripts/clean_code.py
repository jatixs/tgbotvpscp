import io
import os
import tokenize
import re

EXCLUDE_DIRS = {'.git', '.github', '__pycache__', 'venv', 'env', 'tests'}
EXCLUDE_FILES = {'clean_project.py', 'docker-compose.yml', 'requirements.txt', 'clean_code.py'}

def remove_comments_and_docstrings(source_code):
    io_obj = io.StringIO(source_code)
    out = ""
    prev_toktype = tokenize.INDENT
    last_lineno = -1
    last_col = 0
    try:
        tokens = tokenize.generate_tokens(io_obj.readline)
        for tok in tokens:
            token_type = tok.type
            token_string = tok.string
            start_line, start_col = tok.start
            end_line, end_col = tok.end
            if start_line > last_lineno:
                last_col = 0
            if token_type == tokenize.COMMENT:
                pass
            elif token_type == tokenize.STRING:
                if prev_toktype == tokenize.INDENT or prev_toktype == tokenize.NEWLINE or prev_toktype == tokenize.NL:
                    pass
                else:
                    if start_col > last_col:
                        out += (" " * (start_col - last_col))
                    out += token_string
            else:
                if start_col > last_col:
                    out += (" " * (start_col - last_col))
                out += token_string
            prev_toktype = token_type
            last_col = end_col
            last_lineno = end_line
    except tokenize.TokenError:
        return source_code
    return re.sub(r'\n\s*\n\s*\n', '\n\n', out)

def process_directory(root_dir):
    print(f"🚀 CI Cleanup started: {root_dir}")
    for dirpath, dirnames, filenames in os.walk(root_dir):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
        for filename in filenames:
            if not filename.endswith('.py') or filename in EXCLUDE_FILES:
                continue
            full_path = os.path.join(dirpath, filename)
            try:
                with open(full_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                new_content = remove_comments_and_docstrings(content)
                if len(new_content) != len(content):
                    with open(full_path, 'w', encoding='utf-8') as f:
                        f.write(new_content)
                    print(f"✅ Cleaned: {filename}")
            except Exception as e:
                print(f"❌ Error {filename}: {e}")

if __name__ == "__main__":
    # В CI запускаем без вопросов
    process_directory(".")