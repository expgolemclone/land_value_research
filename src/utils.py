import os


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def read_codes(path: str) -> list[str]:
    if not os.path.exists(path):
        return []
    codes: list[str] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            # 4桁証券コードのみを想定
            codes.append(s)
    return codes
