#!/usr/bin/env python3
"""
Tavily Extract CLI - Batch extract web content from multiple URLs and save as markdown files.
Supports extracting multiple URLs and saving to specified directory.
Returns a map of URL to file path.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import List, Dict, Any, Optional, Union
from urllib.parse import urlparse
import re

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


def sanitize_filename(url: str) -> str:
    """Create a safe filename from URL."""
    # Parse URL to get domain and path
    parsed = urlparse(url)
    
    # Get domain (remove www. if present)
    domain = parsed.netloc.replace('www.', '')
    
    # Get path, remove leading/trailing slashes
    path = parsed.path.strip('/')
    
    # If path is empty, use domain only
    if not path:
        filename = domain
    else:
        # Replace path separators with underscores
        path = path.replace('/', '_')
        # Limit path length
        if len(path) > 50:
            path = path[:50]
        filename = f"{domain}_{path}"
    
    # Remove any non-alphanumeric characters (except underscores and hyphens)
    filename = re.sub(r'[^\w\-\.]', '_', filename)
    
    # Limit total length
    if len(filename) > 100:
        filename = filename[:100]
    
    # Add timestamp to avoid collisions
    timestamp = int(time.time())
    return f"{filename}_{timestamp}.md"


class TavilyExtractCLI:
    """Tavily Extract CLI handler for batch URL extraction."""

    API_BASE_URL = "https://api.tavily.com"
    EXTRACT_ENDPOINT = "/extract"

    def __init__(self, api_key: Optional[str] = None):
        """Initialize with API key from .env file, environment, or argument."""
        self.api_key = load_api_key(api_key)

    def extract_urls(self, urls: List[str], **kwargs) -> Dict[str, Any]:
        """
        Extract content from multiple URLs using Tavily Extract API.
        
        Args:
            urls: List of URLs to extract
            **kwargs: Additional API parameters
        
        Returns:
            API response as dictionary
        """
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }

        payload = {"urls": urls}

        # Map CLI arguments to API parameters
        param_mapping = {
            "query": "query",
            "chunks_per_source": "chunks_per_source",
            "extract_depth": "extract_depth",
            "include_images": "include_images",
            "include_favicon": "include_favicon",
            "format": "format",
            "timeout": "timeout",
            "include_usage": "include_usage"
        }

        for cli_param, api_param in param_mapping.items():
            if kwargs.get(cli_param) is not None:
                payload[api_param] = kwargs[cli_param]

        response = requests.post(
            f"{self.API_BASE_URL}{self.EXTRACT_ENDPOINT}",
            headers=headers,
            json=payload,
            timeout=60
        )

        if response.status_code != 200:
            try:
                error_detail = response.json().get("detail", {})
                error_msg = error_detail.get("error", "Unknown error")
            except:
                error_msg = response.text

            raise RuntimeError(f"API Error ({response.status_code}): {error_msg}")

        return response.json()

    def save_to_files(self, results: List[Dict], output_dir: Path) -> Dict[str, str]:
        """
        Save extracted content to markdown files.
        
        Args:
            results: List of extraction results from API
            output_dir: Directory to save files
        
        Returns:
            Dictionary mapping URL to file path
        """
        url_to_file = {}
        
        # Ensure output directory exists
        output_dir.mkdir(parents=True, exist_ok=True)
        
        for result in results:
            url = result.get("url")
            raw_content = result.get("raw_content", "")
            
            if not url or not raw_content:
                continue
            
            # Create filename from URL
            filename = sanitize_filename(url)
            filepath = output_dir / filename
            
            try:
                # Write content to file
                with open(filepath, 'w', encoding='utf-8') as f:
                    # Add metadata header
                    f.write(f"# Extracted from: {url}\n")
                    f.write(f"# Extraction time: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                    f.write(f"# File saved to: {filepath}\n")
                    f.write("\n---\n\n")
                    
                    # Write the actual content
                    f.write(raw_content)
                
                url_to_file[url] = str(filepath)
                
            except Exception as e:
                print(f"Warning: Failed to save {url}: {e}", file=sys.stderr)
        
        return url_to_file

    def extract_and_save(self, urls: List[str], output_dir: str, **kwargs) -> Dict[str, str]:
        """
        Extract URLs and save to files in one operation.
        
        Args:
            urls: List of URLs to extract
            output_dir: Directory to save files
            **kwargs: Additional API parameters
        
        Returns:
            Dictionary mapping URL to file path
        """
        # Validate URLs
        if not urls:
            raise ValueError("No URLs provided")
        
        if len(urls) > 20:
            raise ValueError(f"Maximum 20 URLs allowed, got {len(urls)}")
        
        # Ensure format is markdown
        kwargs["format"] = "markdown"
        
        # Extract content
        print(f"Extracting {len(urls)} URLs...", file=sys.stderr)
        response = self.extract_urls(urls, **kwargs)
        
        # Check for failed results
        failed_results = response.get("failed_results", [])
        if failed_results:
            print(f"Warning: {len(failed_results)} URLs failed:", file=sys.stderr)
            for failed in failed_results:
                print(f"  - {failed.get('url')}: {failed.get('error', 'Unknown error')}", file=sys.stderr)
        
        # Save successful results
        successful_results = response.get("results", [])
        if not successful_results:
            raise RuntimeError("No content extracted from any URL")
        
        print(f"Successfully extracted {len(successful_results)} URLs", file=sys.stderr)
        
        # Save to files
        output_path = Path(output_dir).resolve()
        url_to_file = self.save_to_files(successful_results, output_path)
        
        # Print usage info if available
        usage = response.get("usage", {})
        if usage:
            credits = usage.get("credits", 0)
            print(f"Credits used: {credits}", file=sys.stderr)
        
        return url_to_file


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Batch extract web content from multiple URLs and save as markdown files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Extract single URL
  %(prog)s --urls https://example.com --output ./extracted
  
  # Extract multiple URLs from file
  %(prog)s --urls-file urls.txt --output ./extracted
  
  # Extract with advanced depth and include images
  %(prog)s --urls https://example1.com https://example2.com --output ./extracted \\
           --extract-depth advanced --include-images
  
  # Extract with query for relevance ranking
  %(prog)s --urls https://docs.python.org --output ./extracted \\
           --query "tutorial" --chunks-per-source 5
        """
    )

    # URL sources (mutually exclusive group)
    url_group = parser.add_mutually_exclusive_group(required=True)
    url_group.add_argument(
        "--urls",
        nargs="+",
        help="URLs to extract (space-separated, max 20)"
    )
    url_group.add_argument(
        "--urls-file",
        help="File containing URLs (one per line)"
    )

    # Required arguments
    parser.add_argument(
        "--output", "-o",
        required=True,
        help="Output directory for saved markdown files"
    )

    # Optional arguments
    parser.add_argument(
        "--api-key", "-k",
        help="Tavily API key (default: TAVILY_API_KEY from .env file, environment, or this argument)"
    )

    parser.add_argument(
        "--extract-depth", "-d",
        choices=["basic", "advanced"],
        default="basic",
        help="Extraction depth (default: basic)"
    )

    parser.add_argument(
        "--query", "-q",
        help="Query for relevance ranking of extracted content"
    )

    parser.add_argument(
        "--chunks-per-source",
        type=int,
        choices=range(1, 6),
        default=3,
        help="Maximum chunks per source when query is provided (1-5, default: 3)"
    )

    parser.add_argument(
        "--include-images",
        action="store_true",
        help="Include images in extraction"
    )

    parser.add_argument(
        "--include-favicon",
        action="store_true",
        help="Include favicon URLs"
    )

    parser.add_argument(
        "--timeout",
        type=float,
        choices=range(1, 61),
        metavar="1-60",
        help="Timeout in seconds (1-60)"
    )

    parser.add_argument(
        "--include-usage",
        action="store_true",
        help="Include credit usage information"
    )

    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose output"
    )

    parser.add_argument(
        "--output-format",
        choices=["json", "text"],
        default="json",
        help="Output format for URL-to-file mapping (default: json)"
    )

    return parser.parse_args()


def read_urls_from_file(filepath: str) -> List[str]:
    """Read URLs from file (one per line)."""
    urls = []
    try:
        with open(filepath, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    urls.append(line)
    except Exception as e:
        raise ValueError(f"Failed to read URLs from file {filepath}: {e}")
    
    return urls


def main():
    """Main entry point."""
    args = parse_args()

    try:
        # Load URLs
        if args.urls:
            urls = args.urls
        else:
            urls = read_urls_from_file(args.urls_file)
        
        if not urls:
            raise ValueError("No valid URLs found")
        
        if len(urls) > 20:
            raise ValueError(f"Maximum 20 URLs allowed, got {len(urls)}")
        
        if args.verbose:
            print(f"Processing {len(urls)} URLs:", file=sys.stderr)
            for url in urls:
                print(f"  - {url}", file=sys.stderr)
            print(f"Output directory: {args.output}", file=sys.stderr)

        # Initialize CLI
        cli = TavilyExtractCLI(api_key=args.api_key)

        # Prepare extraction parameters
        extract_params = {
            "extract_depth": args.extract_depth,
            "query": args.query,
            "chunks_per_source": args.chunks_per_source,
            "include_images": args.include_images,
            "include_favicon": args.include_favicon,
            "timeout": args.timeout,
            "include_usage": args.include_usage
        }

        # Remove None values
        extract_params = {k: v for k, v in extract_params.items() if v is not None}

        # Extract and save
        url_to_file = cli.extract_and_save(urls, args.output, **extract_params)

        # Output results
        if args.output_format == "json":
            print(json.dumps(url_to_file, indent=2, ensure_ascii=False))
        else:
            print("URL to file mapping:")
            for url, filepath in url_to_file.items():
                print(f"{url} -> {filepath}")

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