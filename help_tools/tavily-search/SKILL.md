---
name: tavily-search
description: Tavily CLI tools for web search and content extraction. Includes search functionality and batch URL extraction with markdown file saving. 多词查询需加引号,
metadata: {"nanobot":{"emoji":"🔍","requires":{"env":["TAVILY_API_KEY"]}}}
---

# Tavily CLI Tools

This skill provides two command-line interfaces:
1. **Tavily Search CLI** - for web searches using Tavily Search API
2. **Tavily Extract CLI** - for batch extraction of web content from URLs and saving as markdown files

## 1. Tavily Search CLI

A command-line interface for performing web searches using the Tavily Search API. This skill provides a simple wrapper for the Tavily `/search` endpoint with essential parameters.

### Script Usage

The main script `tavily-search.py` supports the following parameters:

#### Required
- `query`: Search query string (positional argument)

#### Optional
- `--max-results`, `-m`: Maximum number of results (default: 5, range: 1-20)
- `--search-depth`, `-d`: Search depth: basic, advanced, fast, ultra-fast (default: basic)
- `--topic`, `-t`: Search topic: general, news, finance (default: general)
- `--include-answer`, `-a`: Include LLM-generated answer: basic, advanced, or true/false (default: false)
- `--output`, `-o`: Output format: json, text (default: text)
- `--verbose`, `-v`: Enable verbose output

#### Examples

News topic search:
```bash
# 多词查询需加引号
./scripts/tavily-search.py "election results" --topic news --max-results 10
```

Search with advanced depth and 10 results:
```bash
# 多词查询需加引号
./scripts/tavily-search.py "climate change" --search-depth advanced --max-results 10
```

Get search results with LLM answer in JSON format:
```bash
# 多词查询需加引号
./scripts/tavily-search.py "who is Elon Musk" --include-answer basic --output json
```


## Error Handling

The scripts provide clear error messages for:
- Missing API key
- Invalid parameters
- API errors (rate limits, authentication, etc.)
- Network connectivity issues

Exit codes:
- `0`: Success
- `1`: General error
- `2`: Invalid arguments
- `3`: API error
- `4`: Missing configuration

## Notes

- Always respect Tavily's terms of service
- For production use, consider implementing caching and retry logic
- Maximum 20 URLs per extraction request