import os
import getpass
import yaml
from pathlib import Path

def _get_openclaw_key(model_name: str) -> str | None:
    """Read ~/.openclaw/config.yaml or ~/.config/openclaw/config.yaml to extract API key for a given model."""
    home = Path.home()
    possible_paths = [
        home / ".openclaw" / "config.yaml",
        home / ".config" / "openclaw" / "config.yaml"
    ]
    
    for path in possible_paths:
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    config = yaml.safe_load(f)
                    # OpenClaw config structure usually places models under a 'providers' or 'models' key
                    # Simplified extraction: searching for known key patterns
                    # If this gets too complex, we fallback to interactive.
                    # As a heuristic, we'll look for standard env dicts if present
                    if isinstance(config, dict):
                        env_vars = config.get("env", {})
                        if isinstance(env_vars, dict):
                            if "gpt" in model_name.lower():
                                return env_vars.get("OPENAI_API_KEY")
                            elif "claude" in model_name.lower() or "anthropic" in model_name.lower():
                                return env_vars.get("ANTHROPIC_API_KEY")
                            elif "gemini" in model_name.lower():
                                return env_vars.get("GEMINI_API_KEY")
            except Exception:
                pass
    return None

def _prompt_user_for_key() -> tuple[str, str]:
    """Interactive prompt for the user to select an LLM provider and enter their key."""
    print("\n" + "="*50)
    print("Welcome to Agentic Flow Enterprise!")
    print("It looks like you don't have an API key configured in .env.")
    print("Please select your primary LLM provider:")
    print("  [1] OpenAI (GPT-4/o1)")
    print("  [2] Anthropic (Claude 3.5)")
    print("  [3] Google (Gemini 1.5/2.0)")
    print("  [4] DeepSeek")
    print("  [0] Skip (I will configure it manually later)")
    print("="*50)
    
    choice = input("Select a provider [1-4]: ").strip()
    
    if choice == "1":
        key_name = "OPENAI_API_KEY"
    elif choice == "2":
        key_name = "ANTHROPIC_API_KEY"
    elif choice == "3":
        key_name = "GEMINI_API_KEY"
    elif choice == "4":
        key_name = "DEEPSEEK_API_KEY"
    else:
        return "", ""
        
    api_key = getpass.getpass(f"Please enter your {key_name} (input will be hidden): ").strip()
    return key_name, api_key

def _save_to_env(key_name: str, key_value: str, env_path: str = ".env"):
    """Append or update the given key/value in the .env file."""
    if not key_name or not key_value:
        return

    # Using standard file I/O to avoid strict dependency on python-dotenv for writing
    try:
        lines = []
        key_found = False
        if os.path.exists(env_path):
            with open(env_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        
        with open(env_path, "w", encoding="utf-8") as f:
            for line in lines:
                if line.strip().startswith(f"{key_name}="):
                    f.write(f'{key_name}="{key_value}"\n')
                    key_found = True
                else:
                    f.write(line)
                    
            if not key_found:
                # Add a newline if the file didn't end with one
                if lines and not lines[-1].endswith("\n"):
                    f.write("\n")
                f.write(f'{key_name}="{key_value}"\n')
                
        # Make sure LITELLM_MASTER_KEY is also set if it's not present
        if not any("LITELLM_MASTER_KEY=" in ln for ln in lines):
            with open(env_path, "a", encoding="utf-8") as f:
                f.write('LITELLM_MASTER_KEY="sk-agentic-flow-default"\n')
                
    except Exception as e:
        print(f"Failed to write to {env_path}: {e}")

def ensure_api_keys():
    """Ensure at least one major standard API key is present in .env. 
    If not, attempt to discover from OpenClaw, else prompt user."""
    # Check if .env exists and has at least one of the major keys
    standard_keys = ["OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "DEEPSEEK_API_KEY"]
    has_key = False
    
    if os.path.exists(".env"):
        with open(".env", "r", encoding="utf-8") as f:
            content = f.read()
            for k in standard_keys:
                if f"{k}=" in content:
                    has_key = True
                    break
                    
    if has_key:
        return
        
    print("\n🔍 No primary LLM API keys found in .env. Attempting discovery...")
    
    # Attempt OpenClaw discovery for default 'gemini' 
    oc_key = _get_openclaw_key("gemini")
    if oc_key:
        print("✅ Automatically discovered Gemini API key from OpenClaw configuration!")
        _save_to_env("GEMINI_API_KEY", oc_key)
        return
        
    oc_key_claude = _get_openclaw_key("claude")
    if oc_key_claude:
        print("✅ Automatically discovered Anthropic API key from OpenClaw configuration!")
        _save_to_env("ANTHROPIC_API_KEY", oc_key_claude)
        return
        
    oc_key_gpt = _get_openclaw_key("gpt")
    if oc_key_gpt:
        print("✅ Automatically discovered OpenAI API key from OpenClaw configuration!")
        _save_to_env("OPENAI_API_KEY", oc_key_gpt)
        return
        
    # If discovery failed, prompt interactively
    key_name, api_key = _prompt_user_for_key()
    if key_name and api_key:
        _save_to_env(key_name, api_key)
        print(f"✅ Successfully securely saved {key_name} to .env")
    else:
        print("⚠️ No API key configured. You may need to manually edit the .env file.")
