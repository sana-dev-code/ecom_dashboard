# DuckDB AI Chatbot — Cursor Project Rules

## Project Overview
We are building a Smart Query Layer on top of a Unified DuckDB e-commerce database.
Users ask questions in natural language (Urdu, Roman Urdu, or English), and the system automatically generates SQL, runs it on DuckDB, and returns results.

## Tech Stack (DO NOT change these)
- **LLM Brain**: Llama 3.3-70B via Groq API (`langchain-groq`)
- **Agent Engine**: LangChain SQL Agent (`create_sql_agent`, `SQLDatabaseToolkit`)
- **Database**: DuckDB (local `.duckdb` file via `duckdb-engine` + SQLAlchemy)
- **Config**: `python-dotenv` for API keys and paths
- **Python version**: 3.10+

## Project File Structure
```
duckdb-ai-chatbot/
├── chatbot.py          # Main entry point (CLI + agent logic)
├── agent.py            # LangChain agent builder (get_llm, get_db, get_agent)
├── db_utils.py         # DuckDB helpers (connect, list tables, run raw queries)
├── demo_data.py        # Creates demo ecommerce.duckdb for testing
├── requirements.txt    # Pinned dependencies
├── .env                # API keys (never commit this)
└── .env.example        # Safe template to commit
```

## .env Variables
```
GROQ_API_KEY=gsk_...          # from console.groq.com
DUCKDB_PATH=ecommerce.duckdb  # path to the unified DuckDB file
MODEL_NAME=llama-3.3-70b-versatile
```

## DuckDB Schema (e-commerce)
```sql
customers  (customer_id, name, email, city, country, joined_date DATE)
products   (product_id, name, category, price DECIMAL, stock INT)
orders     (order_id, customer_id, order_date DATE, status, total_amount DECIMAL)
order_items(item_id, order_id, product_id, quantity INT, unit_price DECIMAL)
-- status values: 'completed' | 'pending' | 'cancelled' | 'refunded'
```

## Coding Rules

### General
- Always use `load_dotenv()` at the top before reading any env variable
- Never hardcode API keys or file paths — always use `os.getenv()`
- All database connections to DuckDB must use `read_only=True` unless explicitly writing
- Use `temperature=0` for the LLM — we need deterministic SQL, not creative answers

### LangChain Agent
- Always use `AgentType.ZERO_SHOT_REACT_DESCRIPTION`
- Always set `handle_parsing_errors=True` to avoid crashes on bad LLM output
- Set `max_iterations=5` to prevent infinite loops
- Always pass `sample_rows_in_table_info=3` so the agent has context about data types
- The agent system prompt must instruct the LLM to:
  - Understand Urdu, Roman Urdu, and English
  - Respond in the same language the user used
  - Use DuckDB SQL syntax (not MySQL/PostgreSQL)
  - Use `STRFTIME` for date formatting in DuckDB

### DuckDB + SQLAlchemy
- Connect via: `create_engine(f"duckdb:///{path}", connect_args={"read_only": True})`
- Use `duckdb-engine` package (not raw duckdb) for SQLAlchemy compatibility
- For raw queries (schema inspection, table listing), use `duckdb.connect()` directly
- Always close raw `duckdb` connections after use

### Error Handling
- Wrap `agent.invoke()` in try/except and return a clean error message
- If `GROQ_API_KEY` is missing, raise a clear `ValueError` with setup instructions
- If the `.duckdb` file is missing, raise `FileNotFoundError` with the path

## What NOT to do
- Do NOT switch to OpenAI, Anthropic, or any other LLM provider
- Do NOT use `SQLite` or `PostgreSQL` — only DuckDB
- Do NOT use `AgentExecutor` directly — use `create_sql_agent` wrapper
- Do NOT use `verbose=False` during development — always show the agent's reasoning steps
- Do NOT write raw SQL manually — the agent handles SQL generation automatically
- Do NOT use async unless specifically asked

## Common Groq Models (use these only)
```
llama-3.3-70b-versatile   ← default (best for SQL tasks)
llama-3.1-8b-instant      ← faster, cheaper (for simple queries)
mixtral-8x7b-32768        ← long context fallback
```

## Running the Project
```bash
# Install dependencies
pip install -r requirements.txt

# Test with demo data (no real DB needed)
python chatbot.py --demo

# Ask a single question
python chatbot.py --question "Top 5 products by revenue?"

# Interactive mode
python chatbot.py
```

## Sample Questions the Agent Must Handle
- "Top 5 products by total revenue?"
- "Karachi mein kitne customers hain?"
- "2024 ka monthly sales trend dikhao"
- "Which category has the highest average order value?"
- "Pending orders ki list do"
- "Sabse zyada khareedne wala customer kaun hai?"