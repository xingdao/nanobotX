# Tavily API Reference Documentation

This directory contains detailed documentation for the Tavily API endpoints beyond basic search functionality.

## Available Documents

### [Search.md](Search.md)
Complete OpenAPI specification for the `/search` endpoint. Includes all parameters, response formats, and error codes.

### [Usage.md](Usage.md)
API usage and account management endpoint documentation. Check credit usage and plan details.

### [extract.md](extract.md)
Tavily Extract endpoint for web content extraction from specific URLs.

### [crawl.md](crawl.md)
Tavily Crawl endpoint for graph-based website traversal and content discovery.

### [demo.md](demo.md)
Simple curl example for the search endpoint.

## API Overview

Tavily provides several endpoints for different web intelligence tasks:

1. **Search** (`/search`) - General web search optimized for LLMs
2. **Extract** (`/extract`) - Extract content from specific URLs
3. **Crawl** (`/crawl`) - Crawl websites with intelligent discovery
4. **Usage** (`/usage`) - Check API key and account usage

## Credit System

- **Search**: 1 credit for basic, 2 credits for advanced depth
- **Extract**: 1 credit per 5 successful URLs (basic), 2 credits per 5 (advanced)
- **Crawl**: Variable based on pages processed
- Free tier: 1,000 credits per month

## Common Parameters

Many endpoints share common parameters:
- `include_answer`: Add LLM-generated answer
- `include_raw_content`: Include cleaned HTML content
- `include_images`: Include image search results
- `include_favicon`: Include favicon URLs
- `include_usage`: Include credit usage in response

## Rate Limits

- Free tier: 100 requests per minute
- Paid tiers: Higher limits based on plan
- See official documentation for current rate limits

## Authentication

All endpoints require Bearer token authentication:
```
Authorization: Bearer tvly-YOUR_API_KEY
```

## Error Handling

Standard HTTP status codes:
- `200`: Success
- `400`: Bad request (invalid parameters)
- `401`: Unauthorized (invalid/missing API key)
- `429`: Rate limit exceeded
- `432`: Plan limit exceeded
- `433`: Pay-as-you-go limit exceeded
- `500`: Internal server error

## Getting Help

- Official documentation: https://docs.tavily.com
- API playground: https://app.tavily.com/playground
- Support: support@tavily.com

---

*Note: This skill focuses on basic search functionality. Use these reference documents for advanced features.*