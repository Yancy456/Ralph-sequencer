#!/usr/bin/env python3
"""
Cross-platform uninstallation script for ralph-sq.

This script uninstalls ralph-sq using pip and optionally removes 
persistent settings and debug files.

Usage:
    python uninstall.py [--full]
    
Options:
    --full     Remove all persistent settings and debug files
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


def uninstall_package() -> bool:
    """Uninstall the package using pip."""
    print("📦 Uninstalling ralph-sq...")
    
    cmd = [sys.executable, "-m", "pip", "uninstall", "-y", "ralph-sq"]
    
    try:
        print(f"🔧 Running: {' '.join(cmd)}\n")
        result = subprocess.run(cmd, check=False)
        
        if result.returncode == 0:
            print("\n✅ Package uninstalled successfully!")
            return True
        else:
            print(f"\n❌ Uninstallation failed with exit code {result.returncode}")
            return False
            
    except Exception as e:
        print(f"\n❌ Error during uninstallation: {e}")
        return False


def clean_files() -> None:
    """Clean up persistent settings and debug files."""
    print("\n🧹 Cleaning up persistent files...")
    
    # Persistent settings
    settings_file = Path.home() / ".ralph-sq-settings.yaml"
    if settings_file.exists():
        try:
            settings_file.unlink()
            print(f"✓ Removed settings: {settings_file}")
        except Exception as e:
            print(f"⚠️  Could not remove settings file: {e}")
    else:
        print("· No persistent settings file found.")

    # Debug directory (checks current directory and project root)
    script_dir = Path(__file__).resolve().parent
    debug_dirs = [Path(".ralph_debug"), script_dir / ".ralph_debug"]
    
    for debug_dir in debug_dirs:
        if debug_dir.exists() and debug_dir.is_dir():
            try:
                shutil.rmtree(debug_dir)
                print(f"✓ Removed debug directory: {debug_dir}")
            except Exception as e:
                print(f"⚠️  Could not remove debug directory {debug_dir}: {e}")
        elif debug_dir.exists():
             print(f"· Found {debug_dir} but it's not a directory.")


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Uninstall ralph-sq and clean up persistent files",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Remove all persistent settings and debug files",
    )
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("🗑️  ralph-sq Uninstallation Script")
    print("=" * 60)
    print()
    
    # Uninstall package
    success = uninstall_package()
    
    # Clean files if requested
    if args.full:
        clean_files()
    else:
        print("\n💡 Note: Persistent settings and debug files were NOT removed.")
        print("   Use 'python uninstall.py --full' to remove them.")
    
    print("\n" + "=" * 60)
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
