#!/usr/bin/env python3
"""
Windows Service Wrapper for Audio Analyzer
Allows running the analyzer as a Windows service using NSSM or SC commands

Usage:
  python service_wrapper.py install    # Install as service
  python service_wrapper.py start      # Start the service
  python service_wrapper.py stop       # Stop the service
  python service_wrapper.py remove     # Remove the service
"""

import os
import sys
import subprocess
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
SERVICE_NAME = "AudioAnalyzerService"
PYTHON_EXE = os.environ.get("PYTHON_EXE", sys.executable)
SCRIPT_PATH = os.path.join(os.path.dirname(__file__), "audio_analyzer.py")
SCRIPT_DIR = os.path.dirname(__file__)

# Alternative: Check if NSSM is available (more robust)
NSSM_PATH = os.environ.get("NSSM_PATH", "nssm")
USE_NSSM = os.path.exists(NSSM_PATH)


def run_command(cmd, description=""):
    """Execute a command and log output"""
    logger.info(f"Running: {' '.join(cmd)}")
    if description:
        logger.info(f"Description: {description}")
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False
        )
        
        if result.stdout:
            logger.info(f"Output: {result.stdout}")
        if result.stderr:
            logger.warning(f"Error output: {result.stderr}")
        
        return result.returncode == 0
    
    except Exception as e:
        logger.error(f"Failed to run command: {e}")
        return False


def check_admin():
    """Check if running as administrator"""
    try:
        import ctypes
        return ctypes.windll.shell.IsUserAnAdmin()
    except (AttributeError, OSError):
        return False


def install_service_nssm():
    """Install service using NSSM"""
    logger.info(f"Installing service with NSSM: {SERVICE_NAME}")
    
    # Remove existing service if present
    run_command(
        [NSSM_PATH, "remove", SERVICE_NAME, "confirm"],
        "Removing existing service"
    )
    
    # Install the service
    success = run_command(
        [NSSM_PATH, "install", SERVICE_NAME, PYTHON_EXE, SCRIPT_PATH],
        "Installing new service"
    )
    
    if success:
        # Configure service to restart on failure
        run_command(
            [NSSM_PATH, "set", SERVICE_NAME, "AppDirectory", SCRIPT_DIR],
            "Setting working directory"
        )
        run_command(
            [NSSM_PATH, "set", SERVICE_NAME, "AppStdout", 
             os.path.join(SCRIPT_DIR, "service_output.log")],
            "Redirecting stdout"
        )
        run_command(
            [NSSM_PATH, "set", SERVICE_NAME, "AppStderr",
             os.path.join(SCRIPT_DIR, "service_error.log")],
            "Redirecting stderr"
        )
    
    return success


def install_service_sc():
    """Install service using Windows SC command (fallback)"""
    logger.info(f"Installing service with SC: {SERVICE_NAME}")
    
    # Create batch wrapper for the service
    batch_path = os.path.join(SCRIPT_DIR, f"{SERVICE_NAME}.bat")
    batch_content = f'''@echo off
"{PYTHON_EXE}" "{SCRIPT_PATH}"
'''
    
    try:
        with open(batch_path, 'w') as f:
            f.write(batch_content)
        logger.info(f"Created batch wrapper: {batch_path}")
    except Exception as e:
        logger.error(f"Failed to create batch wrapper: {e}")
        return False
    
    # Remove existing service if present
    run_command(
        ["sc", "delete", SERVICE_NAME],
        "Removing existing service"
    )
    
    # Install the service
    success = run_command(
        ["sc", "create", SERVICE_NAME, f"binPath= \"{batch_path}\""],
        "Creating service"
    )
    
    if success:
        run_command(
            ["sc", "config", SERVICE_NAME, "start=", "auto"],
            "Setting auto-start"
        )
    
    return success


def start_service():
    """Start the service"""
    if USE_NSSM:
        return run_command(
            [NSSM_PATH, "start", SERVICE_NAME],
            f"Starting {SERVICE_NAME}"
        )
    else:
        return run_command(
            ["sc", "start", SERVICE_NAME],
            f"Starting {SERVICE_NAME}"
        )


def stop_service():
    """Stop the service"""
    if USE_NSSM:
        return run_command(
            [NSSM_PATH, "stop", SERVICE_NAME],
            f"Stopping {SERVICE_NAME}"
        )
    else:
        return run_command(
            ["sc", "stop", SERVICE_NAME],
            f"Stopping {SERVICE_NAME}"
        )


def remove_service():
    """Remove the service"""
    if USE_NSSM:
        return run_command(
            [NSSM_PATH, "remove", SERVICE_NAME, "confirm"],
            f"Removing {SERVICE_NAME}"
        )
    else:
        return run_command(
            ["sc", "delete", SERVICE_NAME],
            f"Removing {SERVICE_NAME}"
        )


def main():
    """Main entry point"""
    if not check_admin():
        logger.error("ERROR: This script must be run as Administrator")
        logger.error("Please right-click and select 'Run as Administrator'")
        sys.exit(1)
    
    if len(sys.argv) < 2:
        print(f"Audio Analyzer Service Wrapper")
        print(f"Usage: python {sys.argv[0]} <command>")
        print()
        print("Commands:")
        print(f"  install  - Install the service")
        print(f"  start    - Start the service")
        print(f"  stop     - Stop the service")
        print(f"  remove   - Remove the service")
        sys.exit(1)
    
    command = sys.argv[1].lower()
    
    logger.info(f"Audio Analyzer Service Wrapper")
    logger.info(f"Service Name: {SERVICE_NAME}")
    logger.info(f"Python: {PYTHON_EXE}")
    logger.info(f"Script: {SCRIPT_PATH}")
    logger.info(f"Using {'NSSM' if USE_NSSM else 'SC'} for service management")
    logger.info("-" * 60)
    
    if command == "install":
        if USE_NSSM:
            success = install_service_nssm()
        else:
            success = install_service_sc()
        
        if success:
            logger.info("Service installed successfully")
            logger.info("Start with: sc start AudioAnalyzerService")
            logger.info("Stop with:  sc stop AudioAnalyzerService")
        else:
            logger.error("Service installation failed")
    
    elif command == "start":
        success = start_service()
        if success:
            logger.info("Service started successfully")
        else:
            logger.error("Failed to start service")
    
    elif command == "stop":
        success = stop_service()
        if success:
            logger.info("Service stopped successfully")
        else:
            logger.error("Failed to stop service")
    
    elif command == "remove":
        stop_service()
        success = remove_service()
        if success:
            logger.info("Service removed successfully")
        else:
            logger.error("Failed to remove service")
    
    else:
        logger.error(f"Unknown command: {command}")
        sys.exit(1)


if __name__ == "__main__":
    main()
