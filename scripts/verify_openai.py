import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.env_loader import load_env_file
from backend.app.services.llm_provider import resolve_provider


def main() -> None:
    load_env_file(ROOT / '.env')
    provider = resolve_provider('openai')
    if provider is None:
        print('OpenAI provider unavailable: missing configuration')
        return
    result = provider.verify()
    print(result)


if __name__ == '__main__':
    main()
