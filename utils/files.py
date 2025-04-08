
def load_list(path):
    return [line.strip() for line in open(path, "r", encoding="utf-8") if line.strip()]

def load_seen(path="data/seen.txt"):
    try:
        return set(open(path, "r", encoding="utf-8").read().splitlines())
    except FileNotFoundError:
        return set()

def save_seen(seen, path="data/seen.txt"):
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(line + "\n" for line in seen)
