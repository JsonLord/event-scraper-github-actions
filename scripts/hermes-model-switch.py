#!/usr/bin/env python3
"""
Hermes Model Switch Command with Auto Context Fetch.

Usage:
    hermes model-switch [options]
    
Options:
    --model MODEL      Model name to switch to
    --provider PROVIDER  Provider name (optional)
    --force            Force refresh from endpoint (ignore cache)
    --dry-run          Show what would be done without making changes
    
This command:
1. Queries the /models endpoint for context_length
2. Falls back to provider config if endpoint doesn't return it
3. Caches results for 24 hours
4. Updates config.yaml with the correct context_length
5. Switches to the specified model
"""

import argparse
import os
import subprocess
import sys

HERMES_HOME = os.path.expanduser("~/.hermes")
CONTEXT_MANAGER = os.path.join(HERMES_HOME, "model-context-manager.py")


def main():
    parser = argparse.ArgumentParser(
        description="Switch model with auto context_length fetch",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument("--model", required=True, help="Model name to switch to")
    parser.add_argument("--provider", help="Provider name (optional)")
    parser.add_argument("--force", action="store_true", help="Force refresh from endpoint")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done")
    
    args = parser.parse_args()
    
    # Step 1: Fetch and update context_length
    cmd = [sys.executable, CONTEXT_MANAGER, "--model", args.model]
    
    if args.force:
        cmd.append("--force")
    
    if args.dry_run:
        cmd.append("--update")  # Will show what would be updated
        print(f"Would run: {' '.join(cmd)}")
        return
    
    cmd.append("--update")
    
    print(f"Fetching context_length for '{args.model}'...", flush=True)
    result = subprocess.run(cmd, capture_output=False)
    
    if result.returncode != 0:
        print(f"Error fetching context_length", file=sys.stderr)
        return 1
    
    # Step 2: Switch model using hermes CLI
    hermes_cmd = ["hermes", "config", "set", "model.model", args.model]
    
    if args.provider:
        hermes_cmd.extend(["model.provider", args.provider])
    
    print(f"\nSwitching to model '{args.model}'...", flush=True)
    subprocess.run(hermes_cmd)
    
    print(f"\nDone! Model switched to '{args.model}'", flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
