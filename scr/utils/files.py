# utils/files.py
def load_list(path):
    with open(path, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]

def load_seen(path="data/seen.txt"):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return set(line.strip() for line in f)
    except FileNotFoundError:
        return set()

def save_seen(seen, path="data/seen.txt"):
    with open(path, "w", encoding="utf-8") as f:
        for item in seen:
            f.write(item + "\n")
