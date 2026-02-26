#!/usr/bin/env python3
"""
Tavily Search CLI - Simple command-line interface for Tavily Search API.
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Optional, Dict, Any

try:
    import requests
except ImportError:
    print("Error: 'requests' library is required. Install with: pip install requests", file=sys.stderr)
    sys.exit(1)


def load_api_key(api_key_arg: Optional[str] = None) -> str:
    """
    Load Tavily API key from (in order of priority):
    1. Command line argument (--api-key)
    2. Environment variable (TAVILY_API_KEY)
    3. .env file in current directory or parent directories
    """
    # 1. Command line argument
    if api_key_arg:
        return api_key_arg

    # 2. Environment variable
    env_key = os.environ.get("TAVILY_API_KEY")
    if env_key:
        return env_key

    # 3. Look for .env file
    current_dir = Path.cwd()
    env_files = []

    # Check current directory and parent directories up to 3 levels
    for depth in range(2):
        check_dir = current_dir
        for _ in range(depth):
            check_dir = check_dir.parent
        env_file = check_dir / ".env"
        if env_file.exists():
            env_files.append(env_file)

    # Try each found .env file
    for env_file in env_files:
        try:
            with open(env_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    if '=' in line:
                        key, value = line.split('=', 1)
                        key = key.strip()
                        value = value.strip()
                        if key == "TAVILY_API_KEY":
                            # Remove quotes if present
                            if value.startswith(('"', "'")) and value.endswith(('"', "'")):
                                value = value[1:-1]
                            return value
        except (IOError, PermissionError):
            continue

    # No API key found
    raise ValueError(
        "API key is required. Set TAVILY_API_KEY in .env file, "
        "as environment variable, or provide via --api-key parameter.\n"
        "Create a .env file with: TAVILY_API_KEY=your_key_here"
    )


class TavilySearchCLI:
    """Tavily Search CLI handler."""

    API_BASE_URL = "https://api.tavily.com"
    SEARCH_ENDPOINT = "/search"

    def __init__(self, api_key: Optional[str] = None):
        """Initialize with API key from .env file, environment, or argument."""
        self.api_key = load_api_key(api_key)

    def search(self, query: str, **kwargs) -> Dict[str, Any]:
        """Execute search with given parameters."""
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }

        payload = {"query": query}

        # Map CLI arguments to API parameters
        param_mapping = {
            "max_results": "max_results",
            "search_depth": "search_depth",
            "topic": "topic",
            "include_answer": "include_answer",
            "time_range": "time_range",
            "include_raw_content": "include_raw_content",
            "include_images": "include_images",
            "include_favicon": "include_favicon",
            "country": "country",
            "auto_parameters": "auto_parameters",
            "include_usage": "include_usage"
        }

        for cli_param, api_param in param_mapping.items():
            if kwargs.get(cli_param) is not None:
                payload[api_param] = kwargs[cli_param]

        response = requests.post(
            f"{self.API_BASE_URL}{self.SEARCH_ENDPOINT}",
            headers=headers,
            json=payload,
            timeout=30
        )

        if response.status_code != 200:
            try:
                error_detail = response.json().get("detail", {})
                error_msg = error_detail.get("error", "Unknown error")
            except:
                error_msg = response.text

            raise RuntimeError(f"API Error ({response.status_code}): {error_msg}")

        return response.json()

    def format_output(self, result: Dict[str, Any], output_format: str) -> str:
        """Format search results for output."""
        if output_format == "json":
            return json.dumps(result, indent=2, ensure_ascii=False)

        # Text format
        lines = []
        lines.append(f"Query: {result.get('query', 'N/A')}")

        if result.get("answer"):
            lines.append(f"\nAnswer: {result.get('answer')}")

        if result.get("results"):
            lines.append(f"\nResults ({len(result['results'])}):")
            for i, item in enumerate(result["results"], 1):
                lines.append(f"\n{i}. {item.get('title', 'No title')}")
                lines.append(f"   URL: {item.get('url', 'N/A')}")
                lines.append(f"   Content: {item.get('content', 'No content')[:200]}...")
                if item.get("score"):
                    lines.append(f"   Score: {item.get('score'):.3f}")

        if result.get("images"):
            lines.append(f"\nImages ({len(result['images'])}):")
            for img in result["images"][:3]:  # Show first 3 images
                lines.append(f"  - {img.get('url', 'N/A')}")

        if result.get("response_time"):
            lines.append(f"\nResponse time: {result.get('response_time')}s")

        if result.get("usage"):
            lines.append(f"Credits used: {result.get('usage', {}).get('credits', 'N/A')}")

        return "\n".join(lines)


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Search the web using Tavily Search API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s "latest AI developments"
  %(prog)s "climate change" --search-depth advanced --max-results 10
  %(prog)s "who is Elon Musk" --include-answer basic --output json
  %(prog)s "election results" --topic news --verbose
        """
    )

    # Required arguments
    parser.add_argument(
        "query",
        help="Search query string"
    )

    # Optional arguments
    parser.add_argument(
        "--api-key", "-k",
        help="Tavily API key (default: TAVILY_API_KEY from .env file, environment, or this argument)"
    )

    parser.add_argument(
        "--max-results", "-m",
        type=int,
        choices=range(1, 21),
        default=5,
        help="Maximum number of results (1-20, default: 5)"
    )

    parser.add_argument(
        "--search-depth", "-d",
        choices=["basic", "advanced", "fast", "ultra-fast"],
        default="basic",
        help="Search depth (default: basic)"
    )

    parser.add_argument(
        "--topic", "-t",
        choices=["general", "news", "finance"],
        default="general",
        help="Search topic (default: general)"
    )

    parser.add_argument(
        "--include-answer", "-a",
        nargs="?",
        const="basic",
        help="Include LLM-generated answer (basic, advanced, or true/false)"
    )

    parser.add_argument(
        "--time-range",
        choices=["day", "week", "month", "year", "d", "w", "m", "y"],
        help="Time range for results"
    )

    parser.add_argument(
        "--output", "-o",
        choices=["json", "text"],
        default="text",
        help="Output format (default: text)"
    )

    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose output"
    )

    # Additional API parameters (less commonly used)
    parser.add_argument(
        "--include-raw-content",
        action="store_true",
        help="Include raw content in results"
    )

    parser.add_argument(
        "--include-images",
        action="store_true",
        help="Include images in results"
    )

    parser.add_argument(
        "--include-favicon",
        action="store_true",
        help="Include favicon URLs"
    )

    parser.add_argument(
        "--country",
        help="Boost results from specific country (ISO code)"
    )

    return parser.parse_args()


def main():
    """Main entry point."""
    args = parse_args()

    try:
        # Initialize CLI
        cli = TavilySearchCLI(api_key=args.api_key)

        if args.verbose:
            print(f"Searching for: {args.query}", file=sys.stderr)
            print(f"Parameters: max_results={args.max_results}, "
                  f"search_depth={args.search_depth}, topic={args.topic}",
                  file=sys.stderr)

        # Prepare search parameters
        search_params = {
            "max_results": args.max_results,
            "search_depth": args.search_depth,
            "topic": args.topic,
            "include_answer": args.include_answer,
            "time_range": args.time_range,
            "include_raw_content": args.include_raw_content,
            "include_images": args.include_images,
            "include_favicon": args.include_favicon,
            "country": args.country
        }

        # Remove None values
        search_params = {k: v for k, v in search_params.items() if v is not None}

        # Execute search
        result = cli.search(args.query, **search_params)

        # Format and output results
        output = cli.format_output(result, args.output)
        print(output)

    except ValueError as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        sys.exit(2)
    except RuntimeError as e:
        print(f"API error: {e}", file=sys.stderr)
        sys.exit(3)
    except requests.exceptions.RequestException as e:
        print(f"Network error: {e}", file=sys.stderr)
        sys.exit(4)
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()