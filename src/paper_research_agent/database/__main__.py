"""Initialize local tables without connecting to MCP or a model provider."""
from paper_research_agent.config import load_settings
from .service import HistoryService


def main():
    service = HistoryService(load_settings())
    service.database.close()
    print('SQLite database initialized; no external API was called.')


if __name__ == '__main__':
    main()
