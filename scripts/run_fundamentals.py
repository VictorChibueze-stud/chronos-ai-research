from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(r"C:\Users\vokor\Documents\Projects\chronos-ai\.env"))

from src.fundamentals.llm.processor import run_fundamentals_intelligence

result = run_fundamentals_intelligence()
print(result)
