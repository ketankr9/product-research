import os
import sys
from dotenv import load_dotenv

# Ensure we can import from the package
sys.path.append(os.getcwd())
load_dotenv()

from product_research.tools import tavily_search_sync

query = 'best camera smartphone under 30000 India 2026 reviews'

# Print only what is passed to the agent from the tools.py function
print(tavily_search_sync(query=query))
