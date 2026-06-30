"""
ARL Manager - Automatic Deezer ARL retrieval and refresh
"""

import os
import time
from time import sleep
from datetime import datetime
import chromedriver_autoinstaller
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from fake_useragent import UserAgent


class ARLManager:
    """Manage Deezer ARL retrieval and refresh"""
    
    def __init__(self, email, password, config_dir='/app/config'):
        """
        Initialize ARL Manager
        
        Args:
            email: Deezer account email
            password: Deezer account password
            config_dir: Directory for ARL persistent storage
        """
        self.email = email
        self.password = password
        self.config_dir = config_dir
        self.arl_file = os.path.join(config_dir, 'arl.txt')
        self.login_url = 'https://www.deezer.com/en/login'
        
        # Detect if running in Docker
        self.is_docker = os.path.exists('/.dockerenv') or os.path.exists(config_dir)
        
    def get_new_arl(self):
        """
        Retrieve a fresh ARL from Deezer using Selenium
        Returns the ARL string or None if failed
        """
        print("🔄 Attempting to retrieve new ARL from Deezer...", flush=True)
        
        # Auto-install chromedriver only outside Docker
        if not self.is_docker:
            try:
                chromedriver_autoinstaller.install()
            except Exception as e:
                print(f"❌ Failed to install chromedriver: {e}", flush=True)
                return None
        
        options = Options()
        ua = UserAgent()
        user_agent = ua.random
        options.add_argument(f'user-agent={user_agent}')
        options.add_argument('--headless=new')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-gpu')
        options.add_argument('--disable-software-rasterizer')
        options.add_argument('--disable-extensions')
        options.add_argument('--disable-setuid-sandbox')
        options.add_argument('--disable-blink-features=AutomationControlled')
        options.add_argument('--log-level=3')  # Suppress logs
        options.add_argument('--remote-debugging-port=9222')
        options.add_argument('--window-size=1920,1080')
        
        # In Docker, use system chrome/chromium
        if self.is_docker:
            chrome_bin = os.getenv('CHROME_BIN', '/usr/bin/chromium')
            if os.path.exists(chrome_bin):
                options.binary_location = chrome_bin
            else:
                print(f"❌ Chrome binary not found at {chrome_bin}", flush=True)
                return None
        
        driver = None
        try:
            # Create Chrome service
            if self.is_docker:
                chromedriver_path = os.getenv('CHROMEDRIVER_PATH', '/usr/bin/chromedriver')
                if not os.path.exists(chromedriver_path):
                    print(f"❌ ChromeDriver not found at {chromedriver_path}", flush=True)
                    return None
                service = Service(executable_path=chromedriver_path)
                driver = webdriver.Chrome(service=service, options=options)
            else:
                driver = webdriver.Chrome(options=options)
            
            wait = WebDriverWait(driver, 20)
            driver.get(self.login_url)
            sleep(5)
            
            # Handle GDPR banner
            self._handle_gdpr(driver)
            sleep(3)
            
            # Fill login form
            email_field = wait.until(EC.presence_of_element_located((By.ID, 'email')))
            email_field.clear()
            email_field.send_keys(self.email)
            sleep(1)
            
            password_field = driver.find_element(By.ID, 'password')
            password_field.clear()
            password_field.send_keys(self.password)
            sleep(1)
            
            # Submit with ENTER key
            password_field.send_keys(Keys.RETURN)
            sleep(10)
            
            # Check for login errors
            current_url = driver.current_url
            if 'login' in current_url or 'signin' in current_url:
                try:
                    error_element = driver.find_element(By.CSS_SELECTOR, '.form-error, .error-message, [class*="error"], [role="alert"]')
                    if error_element and error_element.is_displayed():
                        print(f"❌ Login error: {error_element.text}", flush=True)
                except:
                    pass
                sleep(10)  # Wait longer
            
            # Extract ARL cookie
            cookies = driver.get_cookies()
            for cookie in cookies:
                if cookie['name'] == 'arl':
                    arl = cookie['value']
                    print(f"✅ New ARL retrieved: {arl[:20]}...", flush=True)
                    return arl
            
            print("❌ ARL cookie not found after login", flush=True)
            return None
            
        except Exception as e:
            print(f"❌ Error retrieving ARL: {type(e).__name__}", flush=True)
            return None
            
        finally:
            if driver:
                driver.quit()
    
    def _handle_gdpr(self, driver):
        """Handle GDPR consent banner with multiple strategies"""
        gdpr_scripts = [
            "document.querySelector('#gdpr-btn-accept-all')?.click()",
            "document.querySelector('button[id*=\"accept\"]')?.click()",
            "document.querySelector('.gdpr-modalContainer button')?.click()",
            "document.querySelectorAll('button').forEach(btn => { if(btn.textContent.includes('Accept') || btn.textContent.includes('Agree')) btn.click(); })"
        ]
        
        for script in gdpr_scripts:
            try:
                driver.execute_script(script)
                sleep(1)
            except:
                pass
    
    def save_arl_to_env(self, arl):
        """
        Save the new ARL to persistent storage
        Saves to /app/config/arl.txt (Docker volume or local config)
        """
        if not arl:
            return False
        
        try:
            # Ensure config directory exists
            os.makedirs(self.config_dir, exist_ok=True)
            
            # Write ARL to persistent file
            with open(self.arl_file, 'w') as f:
                f.write(arl)
            
            print(f"💾 ARL saved to {self.arl_file}", flush=True)
            return True
            
        except Exception as e:
            print(f"⚠️  Failed to save ARL: {e}", flush=True)
            return False
    
    def refresh_arl_if_needed(self, dz, current_arl):
        """
        Check if current ARL is valid, if not, get a new one
        Returns: (new_arl, login_success)
        """
        # Try current ARL first
        if current_arl:
            print("🔐 Testing current ARL...", flush=True)
            if dz.login_via_arl(current_arl):
                print("✅ Current ARL is valid", flush=True)
                return current_arl, True
            else:
                print("❌ Current ARL is invalid or expired", flush=True)
        
        # Get new ARL
        new_arl = self.get_new_arl()
        if new_arl:
            # Test the new ARL
            if dz.login_via_arl(new_arl):
                print("✅ New ARL is valid and working", flush=True)
                self.save_arl_to_env(new_arl)
                return new_arl, True
            else:
                print("❌ New ARL failed to authenticate", flush=True)
                return None, False
        
        print("❌ Failed to retrieve new ARL", flush=True)
        return None, False


def create_arl_manager_from_env():
    """
    Create an ARLManager instance from environment variables
    Requires DEEZER_EMAIL and DEEZER_PASSWORD to be set
    """
    email = os.getenv('DEEZER_EMAIL')
    password = os.getenv('DEEZER_PASSWORD')
    
    if not email or not password:
        print("⚠️  DEEZER_EMAIL and DEEZER_PASSWORD not configured - Auto-refresh disabled", flush=True)
        return None
    
    return ARLManager(email, password)


def load_arl_from_persistent_storage(config_dir='/app/config'):
    """
    Load ARL from persistent storage
    Returns the stored ARL or None if not found
    
    Args:
        config_dir: Directory containing arl.txt file
    """
    arl_file = os.path.join(config_dir, 'arl.txt')
    
    if os.path.exists(arl_file):
        try:
            with open(arl_file, 'r') as f:
                arl = f.read().strip()
            if arl:
                print(f"📂 Loaded ARL from persistent storage: {arl[:20]}...", flush=True)
                return arl
        except Exception as e:
            print(f"⚠️  Failed to load ARL from {arl_file}: {e}", flush=True)
    
    return None
