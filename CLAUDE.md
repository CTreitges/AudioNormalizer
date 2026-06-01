# AudioNormalizer - Claude Code Projekt

## MCP Server

### Brave Search (global konfiguriert)
- **Zweck**: Web-Suche bei Bedarf (Fehleranalyse, aktuelle Informationen, Dokumentation)
- **Konfiguration**: Global in `~/.claude.json` unter `mcpServers.brave-search`
- **API-Key**: Hinterlegt als `BRAVE_API_KEY` in der MCP-Umgebung
- **Nutzung**: `WebSearch` Tool oder nach Neustart `mcp__brave-search__brave_web_search` verwenden
- **Wann nutzen**: Bei Fehlerrecherche, aktueller Library-Dokumentation, unbekannten Fehlermeldungen, oder wenn Context7 nicht ausreicht
