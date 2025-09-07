#!/usr/bin/env python3
import argparse
import json
import os
import subprocess
import sys
import shutil
import requests
import tempfile
import zipfile
import hashlib
import concurrent.futures
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse
from typing import Dict, List, Optional

class WinPM:
    def __init__(self):
        self.base_dir = Path(os.getenv('LOCALAPPDATA')) / 'winpm'
        self.config_file = self.base_dir / 'config.json'
        self.packages_file = self.base_dir / 'packages.json'
        self.install_dir = self.base_dir / 'packages'
        self.cache_dir = self.base_dir / 'cache'
        self.repos_dir = self.base_dir / 'repositories'
        
        self.ensure_directories()
        self.load_config()
        
    def ensure_directories(self):
        """Create necessary directories"""
        for directory in [self.base_dir, self.install_dir, self.cache_dir, self.repos_dir]:
            directory.mkdir(exist_ok=True)
            
        # Create default config if it doesn't exist
        if not self.config_file.exists():
            default_config = {
                "repositories": {
                    "main": {
                        "url": "https://raw.githubusercontent.com/your-username/winpm-main/main/",
                        "priority": 1
                    },
                    "extras": {
                        "url": "https://raw.githubusercontent.com/your-username/winpm-extras/main/",
                        "priority": 2
                    }
                },
                "settings": {
                    "auto_update_repos": True,
                    "show_verbose_output": False,
                    "default_repository": "main",
                    "download_timeout": 30,
                    "max_parallel_downloads": 3
                }
            }
            with open(self.config_file, 'w') as f:
                json.dump(default_config, f, indent=2)
    
    def load_config(self):
        """Load configuration"""
        with open(self.config_file, 'r') as f:
            self.config = json.load(f)
    
    def save_config(self):
        """Save configuration"""
        with open(self.config_file, 'w') as f:
            json.dump(self.config, f, indent=2)
    
    def load_packages(self):
        """Load installed packages"""
        if not self.packages_file.exists():
            return {}
        with open(self.packages_file, 'r') as f:
            return json.load(f)
    
    def save_packages(self, packages):
        """Save installed packages"""
        with open(self.packages_file, 'w') as f:
            json.dump(packages, f, indent=2)
    
    def get_repository_url(self, repo_name):
        """Get repository URL by name"""
        return self.config['repositories'].get(repo_name, {}).get('url')
    
    def download_file(self, url, destination):
        """Download a file with progress"""
        try:
            response = requests.get(url, stream=True, timeout=self.config['settings']['download_timeout'])
            response.raise_for_status()
            
            total_size = int(response.headers.get('content-length', 0))
            downloaded = 0
            
            with open(destination, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total_size > 0:
                            percent = (downloaded / total_size) * 100
                            print(f"\rDownloading: {percent:.1f}% ({downloaded}/{total_size} bytes)", end='')
            
            print()  # New line after progress
            return True
        except requests.RequestException as e:
            print(f"\nDownload failed: {e}")
            return False
    
    def update_repositories(self):
        """Update all repository manifests"""
        print("Updating repositories...")
        for repo_name, repo_info in self.config['repositories'].items():
            repo_url = repo_info['url']
            manifest_url = urljoin(repo_url, 'repository.json')
            local_file = self.repos_dir / f"{repo_name}.json"
            
            try:
                response = requests.get(manifest_url, timeout=10)
                response.raise_for_status()
                
                with open(local_file, 'w', encoding='utf-8') as f:
                    json.dump(response.json(), f, indent=2)
                
                print(f"✓ Updated {repo_name} repository")
            except Exception as e:
                print(f"✗ Failed to update {repo_name}: {e}")
    
    def load_repository(self, repo_name):
        """Load repository manifest"""
        repo_file = self.repos_dir / f"{repo_name}.json"
        if not repo_file.exists():
            return None
        
        with open(repo_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def find_package(self, package_name):
        """Find package across all repositories"""
        packages = []
        
        for repo_name in self.config['repositories']:
            repo_data = self.load_repository(repo_name)
            if repo_data and package_name in repo_data['packages']:
                package_info = repo_data['packages'][package_name]
                package_info['repository'] = repo_name
                packages.append(package_info)
        
        return packages
    
    def resolve_dependencies(self, package_info):
        """Resolve package dependencies"""
        dependencies = package_info.get('dependencies', [])
        resolved = []
        
        for dep in dependencies:
            dep_packages = self.find_package(dep)
            if dep_packages:
                resolved.append({
                    'name': dep,
                    'info': dep_packages[0]
                })
            else:
                print(f"Warning: Dependency {dep} not found")
        
        return resolved
    
    def install_package(self, package_name, version=None, repo_name=None):
        """Install a package with dependencies"""
        packages = self.load_packages()
        
        if package_name in packages:
            print(f"Package {package_name} is already installed!")
            return False
        
        # Find package
        if repo_name:
            package_info = self.load_repository(repo_name)['packages'].get(package_name)
        else:
            package_infos = self.find_package(package_name)
            if not package_infos:
                print(f"Package {package_name} not found in any repository!")
                return False
            package_info = package_infos[0]  # Take first match
        
        if not package_info:
            print(f"Package {package_name} not found!")
            return False
        
        # Resolve dependencies
        dependencies = self.resolve_dependencies(package_info)
        for dep in dependencies:
            print(f"Installing dependency: {dep['name']}")
            self.install_package(dep['name'])
        
        # Download and install
        version = version or package_info.get('version', '1.0.0')
        download_url = package_info['url']
        
        print(f"Installing {package_name} {version}...")
        
        # Download package
        download_path = self.cache_dir / f"{package_name}_{version}.zip"
        if not self.download_file(download_url, download_path):
            return False
        
        # Extract package
        package_dir = self.install_dir / package_name
        package_dir.mkdir(exist_ok=True)
        
        try:
            with zipfile.ZipFile(download_path, 'r') as zipf:
                zipf.extractall(package_dir)
        except Exception as e:
            print(f"Failed to extract package: {e}")
            return False
        
        # Register package
        packages[package_name] = {
            'version': version,
            'path': str(package_dir),
            'executable': package_info.get('executable', f"{package_name}.exe"),
            'repository': package_info.get('repository', 'unknown'),
            'install_date': datetime.now().isoformat(),
            'hash': self.calculate_hash(download_path)
        }
        
        self.save_packages(packages)
        
        # Add to PATH (create shim)
        self.create_shim(package_name, package_info)
        
        print(f"✓ Installed {package_name} {version}")
        return True
    
    def calculate_hash(self, file_path):
        """Calculate file hash"""
        hasher = hashlib.sha256()
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hasher.update(chunk)
        return hasher.hexdigest()
    
    def create_shim(self, package_name, package_info):
        """Create executable shim"""
        shim_dir = self.base_dir / 'shims'
        shim_dir.mkdir(exist_ok=True)
        
        executable = package_info.get('executable', f"{package_name}.exe")
        package_dir = self.install_dir / package_name
        actual_exe = package_dir / executable
        
        # Create batch shim
        shim_content = f'''@echo off
"{actual_exe}" %*
'''
        shim_file = shim_dir / f"{package_name}.bat"
        with open(shim_file, 'w') as f:
            f.write(shim_content)
        
        # Add shim directory to PATH (user needs to do this manually)
        print(f"Shim created: {shim_file}")
    
    def uninstall(self, package_name):
        """Uninstall a package"""
        packages = self.load_packages()
        
        if package_name not in packages:
            print(f"Package {package_name} is not installed!")
            return False
        
        # Remove package directory
        package_dir = Path(packages[package_name]['path'])
        if package_dir.exists():
            shutil.rmtree(package_dir)
        
        # Remove shim
        shim_file = self.base_dir / 'shims' / f"{package_name}.bat"
        if shim_file.exists():
            shim_file.unlink()
        
        # Remove from registry
        del packages[package_name]
        self.save_packages(packages)
        
        print(f"✓ Uninstalled {package_name}")
        return True
    
    def list_repositories(self):
        """List all configured repositories"""
        print("Configured repositories:")
        print("-" * 50)
        for repo_name, repo_info in self.config['repositories'].items():
            status = "✓" if (self.repos_dir / f"{repo_name}.json").exists() else "✗"
            print(f"{status} {repo_name:15} {repo_info['url']}")
    
    def add_repository(self, repo_name, repo_url):
        """Add a new repository"""
        if repo_name in self.config['repositories']:
            print(f"Repository {repo_name} already exists!")
            return False
        
        self.config['repositories'][repo_name] = {
            "url": repo_url,
            "priority": len(self.config['repositories']) + 1
        }
        self.save_config()
        
        # Download repository manifest
        manifest_url = urljoin(repo_url, 'repository.json')
        local_file = self.repos_dir / f"{repo_name}.json"
        
        try:
            response = requests.get(manifest_url, timeout=10)
            response.raise_for_status()
            
            with open(local_file, 'w', encoding='utf-8') as f:
                json.dump(response.json(), f, indent=2)
            
            print(f"✓ Added repository {repo_name}")
            return True
        except Exception as e:
            print(f"✗ Failed to add repository: {e}")
            return False
    
    def remove_repository(self, repo_name):
        """Remove a repository"""
        if repo_name not in self.config['repositories']:
            print(f"Repository {repo_name} not found!")
            return False
        
        del self.config['repositories'][repo_name]
        self.save_config()
        
        # Remove local manifest
        manifest_file = self.repos_dir / f"{repo_name}.json"
        if manifest_file.exists():
            manifest_file.unlink()
        
        print(f"✓ Removed repository {repo_name}")
        return True
    
    def search(self, query):
        """Search for packages across all repositories"""
        print(f"Searching for '{query}':")
        print("-" * 60)
        
        found = False
        for repo_name in self.config['repositories']:
            repo_data = self.load_repository(repo_name)
            if not repo_data:
                continue
            
            for pkg_name, pkg_info in repo_data['packages'].items():
                if (query.lower() in pkg_name.lower() or 
                    query.lower() in pkg_info.get('description', '').lower()):
                    
                    installed = pkg_name in self.load_packages()
                    status = "✓" if installed else " "
                    
                    print(f"{status} {pkg_name:20} {pkg_info.get('version', '?'):10} "
                          f"{pkg_info.get('description', 'No description'):30} [{repo_name}]")
                    found = True
        
        if not found:
            print("No packages found matching your query.")
    
    def update(self, package_name=None):
        """Update packages"""
        if package_name:
            print(f"Updating {package_name}...")
            # Single package update logic
        else:
            print("Checking for updates...")
            packages = self.load_packages()
            for pkg_name, pkg_info in packages.items():
                current_version = pkg_info['version']
                available = self.find_package(pkg_name)
                
                if available and available[0]['version'] != current_version:
                    print(f"Update available for {pkg_name}: {current_version} -> {available[0]['version']}")
                    # Add update logic here
    
    def cleanup(self):
        """Clean up cache and temporary files"""
        print("Cleaning up cache...")
        for item in self.cache_dir.iterdir():
            if item.is_file():
                item.unlink()
        print("✓ Cache cleaned")

def main():
    parser = argparse.ArgumentParser(
        description='Windows Package Manager - Advanced package management',
        epilog='Example: winpm install python --repo main'
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Command to execute')
    
    # Install command
    install_parser = subparsers.add_parser('install', help='Install a package')
    install_parser.add_argument('package', help='Package name to install')
    install_parser.add_argument('--version', '-v', help='Specific version to install')
    install_parser.add_argument('--repo', '-r', help='Specific repository to use')
    
    # Uninstall command
    uninstall_parser = subparsers.add_parser('uninstall', help='Uninstall a package')
    uninstall_parser.add_argument('package', help='Package name to uninstall')
    
    # List command
    list_parser = subparsers.add_parser('list', help='List installed packages')
    list_parser.add_argument('--repo', '-r', action='store_true', help='List repositories instead')
    
    # Search command
    search_parser = subparsers.add_parser('search', help='Search for packages')
    search_parser.add_argument('query', help='Search query')
    
    # Update command
    update_parser = subparsers.add_parser('update', help='Update packages or repositories')
    update_parser.add_argument('package', nargs='?', help='Package name to update (optional)')
    
    # Repository management
    repo_parser = subparsers.add_parser('repo', help='Repository management')
    repo_subparsers = repo_parser.add_subparsers(dest='repo_command')
    
    repo_add = repo_subparsers.add_parser('add', help='Add a repository')
    repo_add.add_argument('name', help='Repository name')
    repo_add.add_argument('url', help='Repository URL')
    
    repo_subparsers.add_parser('list', help='List repositories')
    
    repo_remove = repo_subparsers.add_parser('remove', help='Remove a repository')
    repo_remove.add_argument('name', help='Repository name')
    
    # Cleanup command
    subparsers.add_parser('cleanup', help='Clean up cache files')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    pm = WinPM()
    
    try:
        if args.command == 'install':
            pm.install_package(args.package, args.version, args.repo)
        elif args.command == 'uninstall':
            pm.uninstall(args.package)
        elif args.command == 'list':
            if args.repo:
                pm.list_repositories()
            else:
                packages = pm.load_packages()
                if packages:
                    print("Installed packages:")
                    for name, info in packages.items():
                        print(f"  {name:20} {info['version']:10} [{info.get('repository', 'unknown')}]")
                else:
                    print("No packages installed.")
        elif args.command == 'search':
            pm.search(args.query)
        elif args.command == 'update':
            if args.package:
                pm.update(args.package)
            else:
                pm.update_repositories()
                pm.update()
        elif args.command == 'repo':
            if args.repo_command == 'add':
                pm.add_repository(args.name, args.url)
            elif args.repo_command == 'list':
                pm.list_repositories()
            elif args.repo_command == 'remove':
                pm.remove_repository(args.name)
        elif args.command == 'cleanup':
            pm.cleanup()
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    main()