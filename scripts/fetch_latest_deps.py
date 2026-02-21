import urllib.request
import json
import re

def get_latest_version(package):
    url = f"https://pypi.org/pypi/{package}/json"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode())
            return data['info']['version']
    except Exception as e:
        return None

with open('requirements.txt', 'r') as f:
    lines = f.readlines()

new_content = []
for line in lines:
    line = line.strip()
    if not line or line.startswith('#'):
        new_content.append(line)
        continue
    
    match = re.match(r'^([a-zA-Z0-9_\-]+)', line)
    if match:
        pkg = match.group(1)
        # handle extras like passlib[bcrypt]
        full_pkg_match = re.match(r'^([a-zA-Z0-9_\-\[\]]+)', line)
        full_pkg_name = full_pkg_match.group(1) if full_pkg_match else pkg
        
        latest = get_latest_version(pkg)
        if latest:
            new_content.append(f"{full_pkg_name}=={latest}")
        else:
            new_content.append(line) # fallback
    else:
        new_content.append(line)

print('\n'.join(new_content))
