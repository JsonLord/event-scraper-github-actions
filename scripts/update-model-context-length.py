#!/usr/bin/env python3
"""
Fetch context_length from OpenAI-compatible /models endpoint and update Hermes config.

Usage:
    python update-model-context-length.py [--config ~/.hermes/config.yaml] [--provider helmholtz]
"""

import argparse
import json
import os
import sys
import urllib.request
import urllib.error
import yaml

def fetch_models(base_url: str, api_key: str) -> dict:
    """Fetch models from OpenAI-compatible /models endpoint."""
    # base_url might already include /v1, so we need to handle both cases
    base = base_url.rstrip('/')
    if base.endswith('/v1'):
        url = f"{base}/models"
    else:
        url = f"{base}/v1/models"
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode('utf-8'))
    except urllib.error.URLError as e:
        print(f"Error fetching models: {e}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Error parsing JSON response: {e}", file=sys.stderr)
        sys.exit(1)

def find_model_context_length(models_data: dict, target_model: str, provider_config: dict | None = None) -> int | None:
    """Find context_length for a specific model in the models list."""
    data = models_data.get('data', [])
    
    # First, try to find exact match in /models response
    for model in data:
        model_id = model.get('id', '')
        if model_id == target_model:
            # Some APIs return context_length directly, others in a nested structure
            context_length = model.get('context_length') or \
                           model.get('max_context_length') or \
                           model.get('max_tokens') or \
                           model.get('parameters', {}).get('context_length')
            if context_length:
                return int(context_length)
    
    # If not found in /models, try provider config fallback
    if provider_config:
        models_map = provider_config.get('models', {})
        if target_model in models_map:
            ctx = models_map[target_model].get('context_length')
            if ctx:
                print(f"Using context_length from provider config: {ctx}", file=sys.stderr)
                return int(ctx)
    
    # Try prefix matching
    for model in data:
        model_id = model.get('id', '')
        if model_id.startswith(target_model) or target_model.startswith(model_id):
            context_length = model.get('context_length') or \
                           model.get('max_context_length') or \
                           model.get('max_tokens')
            if context_length:
                print(f"Warning: Exact match '{target_model}' not found. Using '{model_id}' context_length: {context_length}", file=sys.stderr)
                return int(context_length)
    
    return None

def update_config(config_path: str, provider_name: str, model_name: str, context_length: int):
    """Update Hermes config.yaml with the new context_length."""
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
    
    # Update the main model config
    if 'model' not in config:
        config['model'] = {}
    
    config['model']['context_length'] = context_length
    config['model']['model'] = model_name
    
    print(f"Updated config: {config_path}")
    print(f"  Model: {model_name}")
    print(f"  Context Length: {context_length}")
    
    # Write back
    with open(config_path, 'w') as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)
    
    print(f"\nConfig updated successfully. Restart Hermes for changes to take effect.")

def main():
    parser = argparse.ArgumentParser(description='Update Hermes config with model context_length from /models endpoint')
    parser.add_argument('--config', default=os.path.expanduser('~/.hermes/config.yaml'),
                       help='Path to Hermes config.yaml (default: ~/.hermes/config.yaml)')
    parser.add_argument('--provider', default=None,
                       help='Provider name to use (default: from config)')
    parser.add_argument('--model', default=None,
                       help='Target model name (default: from config)')
    parser.add_argument('--dry-run', action='store_true',
                       help='Show what would be updated without making changes')
    
    args = parser.parse_args()
    
    # Load config
    if not os.path.exists(args.config):
        print(f"Error: Config file not found: {args.config}", file=sys.stderr)
        sys.exit(1)
    
    with open(args.config, 'r') as f:
        config = yaml.safe_load(f)
    
    # Determine provider settings
    provider_name = args.provider or config.get('model', {}).get('provider', 'custom')
    base_url = config.get('model', {}).get('base_url')
    api_key = config.get('model', {}).get('api_key')
    target_model = args.model or config.get('model', {}).get('model', config.get('model', {}).get('default'))
    
    # Get provider config for fallback - search all providers for matching base_url
    provider_config = None
    providers = config.get('providers', {})
    for pname, pconfig_str in providers.items():
        try:
            pconfig = json.loads(pconfig_str)
            if pconfig.get('base_url') == base_url:
                provider_config = pconfig
                print(f"Found provider config for '{pname}'", file=sys.stderr)
                break
        except (json.JSONDecodeError, TypeError):
            pass  # Skip invalid provider configs
    
    if not base_url:
        print("Error: No base_url found in config. Set model.base_url in config.yaml", file=sys.stderr)
        sys.exit(1)
    
    if not api_key:
        print("Error: No api_key found in config. Set model.api_key in config.yaml or via env var", file=sys.stderr)
        sys.exit(1)
    
    print(f"Fetching models from: {base_url}/v1/models")
    print(f"Target model: {target_model}")
    print()
    
    # Fetch models
    models_data = fetch_models(base_url, api_key)
    
    # Find context_length
    context_length = find_model_context_length(models_data, target_model, provider_config)
    
    if context_length is None:
        print(f"Error: Could not find context_length for model '{target_model}'", file=sys.stderr)
        print("Available models:", file=sys.stderr)
        for model in models_data.get('data', []):
            print(f"  - {model.get('id')}", file=sys.stderr)
        sys.exit(1)
    
    print(f"Found context_length: {context_length}")
    print()
    
    if args.dry_run:
        print("DRY RUN - No changes made")
        print(f"Would update {args.config}:")
        print(f"  model.context_length: 0 -> {context_length}")
        print(f"  model.model: {config.get('model', {}).get('model')} -> {target_model}")
        sys.exit(0)
    
    # Update config
    update_config(args.config, provider_name, target_model, context_length)

if __name__ == '__main__':
    main()
