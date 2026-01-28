#!/usr/bin/env python3
"""
Cross-platform installation script for ralph-py.

This script installs ralph-py globally using pip, ensuring cross-platform
compatibility across Windows, Linux, and macOS.

Usage:
    python install.py [--dev] [--user]
    
Options:
    --dev      Install with development dependencies
    --user     Install to user site-packages instead of system-wide
"""

import argparse
import os
import platform
import subprocess
import sys
from pathlib import Path


def check_python_version() -> bool:
    """Check if Python version meets requirements (>=3.10)."""
    version = sys.version_info
    if version.major < 3 or (version.major == 3 and version.minor < 10):
        print(f"❌ Error: Python 3.10+ is required, but found {version.major}.{version.minor}")
        return False
    print(f"✓ Python {version.major}.{version.minor}.{version.micro} detected")
    return True


def check_pip() -> bool:
    """Check if pip is available."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "--version"],
            capture_output=True,
            text=True,
            check=True,
        )
        print(f"✓ pip found: {result.stdout.strip()}")
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("❌ Error: pip is not available")
        print("Please install pip first: https://pip.pypa.io/en/stable/installation/")
        return False


def get_project_root() -> Path:
    """Get the project root directory (where this script is located)."""
    # Get the directory where this script is located
    script_path = Path(__file__).resolve()
    return script_path.parent


def install_package(dev: bool = False, user: bool = False) -> bool:
    """Install the package using pip."""
    project_root = get_project_root()
    pyproject_path = project_root / "pyproject.toml"
    
    if not pyproject_path.exists():
        print(f"❌ Error: pyproject.toml not found at {pyproject_path}")
        return False
    
    print(f"\n📦 Installing ralph-py from {project_root}")
    
    # Build pip install command
    cmd = [sys.executable, "-m", "pip", "install"]
    
    if user:
        cmd.append("--user")
        print("  → Installing to user site-packages")
    else:
        print("  → Installing system-wide (may require admin/sudo)")
    
    if dev:
        cmd.append("-e")
        cmd.append(".[dev]")
        print("  → Installing in editable mode with dev dependencies")
    else:
        cmd.append("-e")
        cmd.append(".")
        print("  → Installing in editable mode")
    
    # Change to project root directory
    original_cwd = os.getcwd()
    try:
        os.chdir(project_root)
        
        print(f"\n🔧 Running: {' '.join(cmd)}\n")
        
        # Run pip install
        result = subprocess.run(
            cmd,
            check=False,
        )
        
        if result.returncode == 0:
            print("\n✅ Installation successful!")
            
            # Check if the command is available
            check_command_available()
            return True
        else:
            print(f"\n❌ Installation failed with exit code {result.returncode}")
            if not user and platform.system() != "Windows":
                print("\n💡 Tip: If you got a permission error, try:")
                print("   - Using --user flag: python install.py --user")
                print("   - Or use sudo: sudo python install.py")
            return False
            
    except KeyboardInterrupt:
        print("\n\n⚠️  Installation interrupted by user")
        return False
    except Exception as e:
        print(f"\n❌ Error during installation: {e}")
        return False
    finally:
        os.chdir(original_cwd)


def check_command_available() -> None:
    """Check if the ralph-py command is available after installation."""
    print("\n🔍 Verifying installation...")
    
    # Check if command exists
    try:
        result = subprocess.run(
            ["ralph-py", "--help"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            print("✓ ralph-py command is available")
            print("\n📖 Usage:")
            print("   ralph-py run -p \"your prompt\"")
            print("   ralph-py --help")
        else:
            print("⚠️  ralph-py command found but returned an error")
    except FileNotFoundError:
        print("⚠️  ralph-py command not found in PATH")
        print("\n💡 The package is installed, but the command may not be in your PATH.")
        if platform.system() == "Windows":
            print("   On Windows, you may need to restart your terminal or add")
            print("   Python Scripts directory to your PATH.")
        else:
            print("   If you used --user flag, make sure ~/.local/bin is in your PATH.")
            print("   You can add it with: export PATH=\"$HOME/.local/bin:$PATH\"")
    except subprocess.TimeoutExpired:
        print("⚠️  Command check timed out")
    except Exception as e:
        print(f"⚠️  Could not verify command: {e}")


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Install ralph-py globally (cross-platform)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python install.py              # Install system-wide
  python install.py --user       # Install to user directory
  python install.py --dev         # Install with dev dependencies
  python install.py --user --dev  # Install with dev deps to user directory
        """,
    )
    parser.add_argument(
        "--dev",
        action="store_true",
        help="Install with development dependencies",
    )
    parser.add_argument(
        "--user",
        action="store_true",
        help="Install to user site-packages instead of system-wide",
    )
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("🚀 ralph-py Installation Script")
    print("=" * 60)
    print(f"Platform: {platform.system()} {platform.release()}")
    print()
    
    # Pre-flight checks
    if not check_python_version():
        return 1
    
    if not check_pip():
        return 1
    
    # Install package
    success = install_package(dev=args.dev, user=args.user)
    
    print("\n" + "=" * 60)
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
