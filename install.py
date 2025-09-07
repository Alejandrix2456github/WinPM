#!/usr/bin/env python3
import os
import shutil
import sys
from pathlib import Path

def install_winpm():
    # Install to user's local app data instead of Program Files
    target_dir = Path(os.getenv('LOCALAPPDATA')) / 'WinPM'
    target_dir.mkdir(exist_ok=True)
    
    # Copy the main script
    script_path = Path(__file__).parent / 'winpm.py'
    target_script = target_dir / 'winpm.py'
    shutil.copy2(script_path, target_script)
    
    # Create batch file wrapper
    batch_content = f'''@echo off
python "{target_script}" %*
'''
    batch_file = target_dir / 'winpm.bat'
    with open(batch_file, 'w') as f:
        f.write(batch_content)
    
    # Create PowerShell wrapper (optional)
    ps_content = f'''#!/usr/bin/env pwsh
python "{target_script}" $args
'''
    ps_file = target_dir / 'winpm.ps1'
    with open(ps_file, 'w') as f:
        f.write(ps_content)
    
    print(f"WinPM installed to {target_dir}")
    print("Please add the following to your PATH environment variable:")
    print(f"  {target_dir}")
    print("\nYou can add it temporarily with:")
    print(f"  set PATH=%PATH%;{target_dir}")
    print("\nOr permanently with:")
    print(f'  setx PATH "%PATH%;{target_dir}"')
    
    return True

if __name__ == '__main__':
    install_winpm()
