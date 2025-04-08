def load_list_from_file(path):
    with open(path, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]

def load_seen(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return [line.strip() for line in f if line.strip()]
    except FileNotFoundError:
        return []

def save_seen(path, seen_list):
    with open(path, "w", encoding="utf-8") as f:
        for item in seen_list:
            f.write(item + "\n")