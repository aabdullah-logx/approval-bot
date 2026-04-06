import os
import time
from datetime import datetime
from sys import platform
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from gologin import GoLogin
import settings
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
import pandas as pd
from dotenv import load_dotenv
import re

# Load environment variables
load_dotenv()





def load_web_driver_with_gologin(profile_id):
    try:
        print(f"Launching GoLogin profile: {profile_id}")
        # Set a custom tmpdir to avoid path length or permission issues in Windows Temp
        tmp_path = os.path.join(os.getcwd(), 'gologin_temp')
        if not os.path.exists(tmp_path):
            os.makedirs(tmp_path)
            
        gl = GoLogin({
            'token': settings.token,
            'profile_id': profile_id,
            'tmpdir': tmp_path
        })

        debugger_address = gl.start()

        chrome_options = Options()
        chrome_options.add_experimental_option("debuggerAddress", debugger_address)
        chrome_options.add_argument("start-maximized")
        chrome_options.add_argument("--window-size=1920x1080")
        chrome_options.add_argument("--no-sandbox")
        

        if platform == "win32":
            local_chromedriver_path = os.getenv('CHROMEDRIVER_WINDOWS', 'chromedriver.exe')
        elif platform in ("linux", "linux2"):
            local_chromedriver_path = os.getenv('CHROMEDRIVER_LINUX', './chromedriver_linux')
        else:
            local_chromedriver_path = os.getenv('CHROMEDRIVER_MAC', './chromedriver')

        driver = webdriver.Chrome(service=Service(local_chromedriver_path), options=chrome_options)
        return driver, gl
    except Exception as e:
        print(f"Error launching GoLogin profile: {e}")
        return None, None


def open_approval_required_inventory(driver, base_url, page_number=1):
    """Open inventory page with approval required filter applied."""
    page_size = 10
    inventory_url = f"{base_url}myinventory/inventory/views/fix-issues?fulfilledBy=all&pageSize={page_size}&sort=date_created_desc&status=approval_required&page={page_number}"
    
    print(f"Opening approval required inventory page {page_number}...")
    driver.get(inventory_url)
    time.sleep(6)
    
    return inventory_url


def asin_exists_in_sheet(worksheet, asin):
    """Check if an ASIN already exists in the worksheet to prevent duplicates."""
    if not worksheet or not asin:
        return False
    try:
        existing_asins = worksheet.col_values(1)  # Column 1 = ASIN
        return str(asin).strip() in [str(a).strip() for a in existing_asins]
    except Exception:
        return False


def check_and_log_document_requirements(driver, asin, title, sku, worksheet=None):
    """Check what documents are required on the current page and log to Google Sheets."""
    try:
        # Check for "Your account does not qualify" heading first
        does_not_qualify = driver.execute_script("""
            var heading = document.getElementById('myq-performance-check-heading-failure');
            if (heading && heading.innerText.toLowerCase().includes('does not qualify')) {
                return true;
            }
            return false;
        """)
        
        if does_not_qualify:
            print(f"  ASIN {asin}: Account does not qualify (document requirements page)")
            if worksheet and not asin_exists_in_sheet(worksheet, asin):
                try:
                    worksheet.append_row([asin, sku, title, 'do_not_qualify'])
                    print(f"  Saved to Google Sheet: {asin} -> do_not_qualify")
                except Exception as w_err:
                    print(f"  Error appending to worksheet: {w_err}")
            elif worksheet:
                print(f"  SKIP: {asin} already in sheet")
            return
        
        reqs = driver.execute_script("""
            var requirements = [];
            
            // Check for Transparency Serial Number (in body or shadow roots)
            var bodyText = (document.body.innerText || "").toLowerCase();
            if (bodyText.includes("transparency serial number") || bodyText.includes("transparency listing application")) {
                requirements.push("transparency serial number");
            } else {
                var allElements = document.querySelectorAll('*');
                for (var j = 0; j < allElements.length; j++) {
                    if (allElements[j].shadowRoot) {
                        var shadowText = (allElements[j].shadowRoot.textContent || "").toLowerCase();
                        if (shadowText.includes("transparency serial number") || shadowText.includes("transparency listing application")) {
                            requirements.push("transparency serial number");
                            break;
                        }
                    }
                }
            }

            // Check for document upload section explicitly
            var renderer = document.getElementById('document_upload_new:renderer');
            if (renderer) {
                var headings = renderer.querySelectorAll('h6');
                for (var i = 0; i < headings.length; i++) {
                    requirements.push(headings[i].innerText.trim());
                }
            } else {
                // Check body text for keywords near requirements
                var allEls = document.querySelectorAll('h3, h6, .a-text-bold, p');
                for(var i=0; i<allEls.length; i++) {
                    var text = allEls[i].innerText.toLowerCase();
                    if(text.includes('invoice') || text.includes('letter of authorization')) {
                        requirements.push(allEls[i].innerText.trim());
                    }
                }
            }
            return [...new Set(requirements.filter(Boolean))];
        """)
        
        status = "unknown"
        if reqs:
            status = "other_docs_needed"
            
            has_invoice = False
            has_transparency = False
            
            for req in reqs:
                if 'transparency serial number' in req.lower() or 'transparency listing' in req.lower():
                    has_transparency = True
                if 'invoice' in req.lower():
                    has_invoice = True

            if has_transparency:
                status = "transparency_number_required"
            elif has_invoice:
                status = "invoice_needed"
        
        doc_string = " | ".join(reqs) if reqs else "None detected"
        
        # Log to Google Sheets (with duplicate check)
        if worksheet and not asin_exists_in_sheet(worksheet, asin):
            try:
                worksheet.append_row([asin, sku, title, status])
                print(f"  Saved to Google Sheet: {asin} -> {status}")
            except Exception as w_err:
                print(f"  Error appending to worksheet: {w_err}")
        elif worksheet:
            print(f"  SKIP: {asin} already in sheet")
            
    except Exception as e:
        print(f"  Error checking documents: {e}")


def extract_first_product_and_click_fix_listing(driver, product_index=0):
    """Click 'Fix listing issue' on the Nth product row, wait for sidebar panel to open,
    then extract ASIN, SKU, and Title from the sidebar panel content.
    
    Flow:
    1. Find div[data-sku] product row at given index
    2. Click its kat-link[label='Fix listing issue'] 
    3. Wait for sidebar panel (kat-panel / div[role='dialog']) to open
    4. Extract ASIN, SKU, Title from sidebar content
    """
    try:
        # print(f"  Step 1: Clicking 'Fix listing issue' on product {product_index + 1}...")
        
        # Click "Fix listing issue" on the Nth product row
        click_result = driver.execute_script("""
            var result = {success: false, method: 'not found', debug: []};
            var idx = arguments[0];
            
            // Get the product row at given index
            var productRows = document.querySelectorAll('div[data-sku]');
            result.debug.push('Found ' + productRows.length + ' product rows');
            
            if (productRows.length === 0 || idx >= productRows.length) {
                result.debug.push('No product row found at index ' + idx);
                return result;
            }
            var firstRow = productRows[idx];
            result.debug.push('Row ' + idx + ' SKU: ' + firstRow.getAttribute('data-sku'));
            
            // Find kat-link with label="Fix listing issue" inside this row
            var katLink = firstRow.querySelector('kat-link[label="Fix listing issue"]');
            if (!katLink) {
                var allKatLinks = firstRow.querySelectorAll('kat-link');
                for (var i = 0; i < allKatLinks.length; i++) {
                    var lbl = (allKatLinks[i].getAttribute('label') || '').toLowerCase();
                    if (lbl.includes('fix listing')) {
                        katLink = allKatLinks[i];
                        break;
                    }
                }
            }
            
            result.debug.push('kat-link found: ' + (katLink ? 'YES' : 'NO'));
            
            if (katLink) {
                // Click the anchor inside shadow DOM
                if (katLink.shadowRoot) {
                    var shadowAnchor = katLink.shadowRoot.querySelector('a');
                    if (shadowAnchor) {
                        shadowAnchor.click();
                        result.success = true;
                        result.method = 'shadow DOM anchor click';
                        return result;
                    }
                }
                // Fallback: direct click
                katLink.click();
                result.success = true;
                result.method = 'direct click';
                return result;
            }
            
            // Fallback: search all kat-links on page
            var allPageLinks = document.querySelectorAll('kat-link[label="Fix listing issue"]');
            result.debug.push('Page-level kat-links: ' + allPageLinks.length);
            if (allPageLinks.length > idx) {
                var link = allPageLinks[idx];
                if (link.shadowRoot) {
                    var sa = link.shadowRoot.querySelector('a');
                    if (sa) { sa.click(); result.success = true; result.method = 'page-level shadow click'; return result; }
                }
                link.click();
                result.success = true;
                result.method = 'page-level direct click';
                return result;
            }
            
            result.debug.push('No Fix listing issue link found at index ' + idx);
            return result;
        """, product_index)
        
        if not click_result.get('success'):
            print(f"  Failed to click 'Fix listing issue' on product {product_index + 1}")
            return None
        
        time.sleep(18)
        
        panel_data = driver.execute_script("""
            var result = {asin: null, sku: null, title: null, debug: [], panel_found: false};
            
            // Find the sidebar panel - it's a kat-panel element
            var panel = document.querySelector('kat-panel');
            if (!panel) {
                panel = document.querySelector('[role="dialog"][aria-label="panel"]');
            }
            if (!panel) {
                var dialogs = document.querySelectorAll('[role="dialog"]');
                for (var d = 0; d < dialogs.length; d++) {
                    if (dialogs[d].offsetParent !== null || dialogs[d].style.display !== 'none') {
                        panel = dialogs[d];
                        break;
                    }
                }
            }
            
            if (!panel) {
                result.debug.push('No sidebar panel found');
                return result;
            }
            
            result.panel_found = true;
            result.debug.push('Sidebar panel found: ' + panel.tagName);
            
            // For kat-panel: content is in light DOM (children of kat-panel element)
            // But innerText on the host may return empty due to shadow DOM slots
            // So we need to get text from the light DOM children directly
            var panelText = '';
            
            // Method 1: Try getting text from light DOM children of kat-panel
            var children = panel.children;
            for (var c = 0; c < children.length; c++) {
                panelText += (children[c].innerText || children[c].textContent || '') + '\\n';
            }
            
            // Method 2: If still empty, try shadow root's .content slot
            if (panelText.trim().length === 0 && panel.shadowRoot) {
                result.debug.push('Light DOM empty, checking shadow root...');
                var contentDiv = panel.shadowRoot.querySelector('.content');
                if (contentDiv) {
                    var slot = contentDiv.querySelector('slot');
                    if (slot) {
                        var assigned = slot.assignedNodes();
                        result.debug.push('Slot assigned nodes: ' + assigned.length);
                        for (var a = 0; a < assigned.length; a++) {
                            panelText += (assigned[a].innerText || assigned[a].textContent || '') + '\\n';
                        }
                    }
                    // Also try direct content text
                    if (panelText.trim().length === 0) {
                        panelText = (contentDiv.innerText || contentDiv.textContent || '');
                    }
                }
                // Also try the entire shadow root text
                if (panelText.trim().length === 0) {
                    panelText = (panel.shadowRoot.textContent || '');
                }
            }
            
            // Method 3: If still empty, try innerHTML parsing
            if (panelText.trim().length === 0) {
                panelText = (panel.innerText || panel.textContent || '');
            }
            
            result.debug.push('Panel text length: ' + panelText.length);
            
            // Extract ASIN - look for pattern ASIN: XXXXXXXXXX or ASIN XXXXXXXXXX
            var asinMatch = panelText.match(/ASIN[:\\s]+([A-Z0-9]{10})/);
            if (asinMatch) {
                result.asin = asinMatch[1];
                result.debug.push('ASIN from panel text: ' + result.asin);
            }
            
            // Extract SKU - look for pattern SKU: XXXX or SKU XXXX
            var skuMatch = panelText.match(/SKU[:\\s]+([^\\s\\n]+)/);
            if (skuMatch) {
                result.sku = skuMatch[1];
                result.debug.push('SKU from panel text: ' + result.sku);
            }
            
            // Extract Title - look for product link with /dp/ href
            var titleLink = panel.querySelector('a[href*="/dp/"][target="_blank"]');
            if (titleLink) {
                result.title = (titleLink.innerText || titleLink.textContent || '').trim();
                result.debug.push('Title from panel link: ' + (result.title || '').substring(0, 60));
                
                // Also get ASIN from href if not found yet
                if (!result.asin) {
                    var hrefMatch = titleLink.getAttribute('href').match(/\\/dp\\/([A-Z0-9]{10})/);
                    if (hrefMatch) {
                        result.asin = hrefMatch[1];
                        result.debug.push('ASIN from panel href: ' + result.asin);
                    }
                }
            }
            
            // If title not found via link, look for product name in panel
            if (!result.title) {
                // Try h1, h2, h3 headings
                var headings = panel.querySelectorAll('h1, h2, h3, h4');
                for (var h = 0; h < headings.length; h++) {
                    var hText = (headings[h].innerText || '').trim();
                    if (hText.length > 10 && !hText.toLowerCase().includes('fix') && !hText.toLowerCase().includes('approval')) {
                        result.title = hText;
                        result.debug.push('Title from heading: ' + hText.substring(0, 60));
                        break;
                    }
                }
            }
            
            // If title still not found, try bold/strong text or first long text in panel
            if (!result.title) {
                var boldTexts = panel.querySelectorAll('b, strong, [class*="title"], [class*="Title"]');
                for (var b = 0; b < boldTexts.length; b++) {
                    var bText = (boldTexts[b].innerText || '').trim();
                    if (bText.length > 15 && !bText.toLowerCase().includes('fix') && !bText.toLowerCase().includes('listing status')) {
                        result.title = bText;
                        result.debug.push('Title from bold text: ' + bText.substring(0, 60));
                        break;
                    }
                }
            }
            
            // Also try all links in panel for title
            if (!result.title) {
                var panelLinks = panel.querySelectorAll('a[target="_blank"]');
                for (var pl = 0; pl < panelLinks.length; pl++) {
                    var plText = (panelLinks[pl].innerText || '').trim();
                    if (plText.length > 15) {
                        result.title = plText;
                        result.debug.push('Title from panel link (fallback): ' + plText.substring(0, 60));
                        break;
                    }
                }
            }
            
            // Extract from span elements near ASIN/SKU labels
            if (!result.asin || !result.sku) {
                var spans = panel.querySelectorAll('span, div');
                for (var s = 0; s < spans.length; s++) {
                    var sText = (spans[s].innerText || '').trim();
                    if (sText === 'ASIN' && !result.asin && spans[s].nextElementSibling) {
                        var nextText = (spans[s].nextElementSibling.innerText || '').trim();
                        if (/^[A-Z0-9]{10}$/.test(nextText)) {
                            result.asin = nextText;
                            result.debug.push('ASIN from span sibling: ' + nextText);
                        }
                    }
                    if (sText === 'SKU' && !result.sku && spans[s].nextElementSibling) {
                        var nextSkuText = (spans[s].nextElementSibling.innerText || '').trim();
                        if (nextSkuText.length > 0) {
                            result.sku = nextSkuText;
                            result.debug.push('SKU from span sibling: ' + nextSkuText);
                        }
                    }
                }
            }
            
            // Log first 300 chars of panel text for debugging
            result.debug.push('Panel text preview: ' + panelText.substring(0, 300).replace(/\\n/g, ' | '));
            
            return result;
        """)
        
        asin = panel_data.get('asin')
        sku = panel_data.get('sku')
        title = panel_data.get('title')
        panel_found = panel_data.get('panel_found', False)
        
        # If any essential data is missing, use the table row as a fallback
        if not panel_found or not asin or not sku or not title:
            if not panel_found:
                print("  WARNING: Sidebar panel not found!")
                
            fallback = driver.execute_script("""
                var row = document.querySelectorAll('div[data-sku]')[0];
                if (!row) return null;
                var sku = row.getAttribute('data-sku');
                var link = row.querySelector('a[href*="/dp/"][target="_blank"]');
                var asin = null, title = null;
                if (link) {
                    title = (link.innerText || '').trim();
                    var m = link.getAttribute('href').match(/\\/dp\\/([A-Z0-9]{10})/);
                    if (m) asin = m[1];
                }
                return {asin: asin, sku: sku, title: title};
            """)
            if fallback:
                asin = asin or fallback.get('asin')
                sku = sku or fallback.get('sku')
                title = title or fallback.get('title')
        
        if not asin and not sku and not title:
            print("  No product details found")
            return None
        
        # Clean SKU - remove trailing words that get concatenated (e.g. "Product", "Listing", etc.)
        if sku:
            sku = re.sub(r'(Product|Listing|Inactive|Active|Offer|Request|Reason).*$', '', sku, flags=re.IGNORECASE).strip()
        
        print(f"  ASIN: {asin} | SKU: {sku} | Title: {title}")
        
        if panel_found:
            req_click = driver.execute_script("""
                var result = {success: false, method: 'not found', debug: []};
                
                var panel = document.querySelector('kat-panel');
                if (!panel) panel = document.querySelector('[role="dialog"][aria-label="panel"]');
                if (!panel) {
                    var dialogs = document.querySelectorAll('[role="dialog"]');
                    for (var d = 0; d < dialogs.length; d++) {
                        if (dialogs[d].offsetParent !== null || dialogs[d].style.display !== 'none') {
                            panel = dialogs[d]; break;
                        }
                    }
                }
                
                if (!panel) return result;
                
                var buttons = panel.querySelectorAll('kat-button, button, a[role="button"], input[type="submit"]');
                for (var i = 0; i < buttons.length; i++) {
                    var targetBtn = buttons[i];
                    if (targetBtn.hasAttribute('disabled') || targetBtn.getAttribute('aria-disabled') === 'true') continue;
                    
                    var btnText = (targetBtn.innerText || targetBtn.value || targetBtn.getAttribute('label') || '').toLowerCase();
                    if (btnText.includes('request approval')) {
                        result.success = true;
                        result.element = targetBtn;
                        return result;
                    }
                }
                
                return result;
            """)
                
            if req_click.get('success'):
                btn_elem = req_click.get('element')
                if btn_elem:
                    try:
                        ActionChains(driver).move_to_element(btn_elem).click().perform()
                        # print("  Clicked 'Request approval' in sidebar.")
                    except Exception as e:
                        print(f"  Failed to click 'Request approval': {e}")
                time.sleep(5)
            else:
                print("  'Request approval' button not found in sidebar.")
        
        return {
            'success': True,
            'asin': asin,
            'sku': sku,
            'title': title,
            'message': f"Clicked Fix via {click_result.get('method')}, panel_found={panel_found}"
        }
            
    except Exception as e:
        print(f"  Error: {e}")
        return None


def process_approval_page(driver, asin, title, sku, worksheet=None):
    """Process the approval page after clicking Fix listing issue."""
    
    # Check what page we landed on
    # current_url = driver.current_url
    # page_title = driver.title
    # print(f"  Current page: {page_title}")
    
    # Check page content
    try:
        page_info = driver.execute_script("""
        var bodyText = document.body.innerText.toLowerCase();
        
        // Check for "We are not accepting applications to sell" element
        var notAccepting = false;
        var boldSpans = document.querySelectorAll('span.a-text-bold');
        for (var i = 0; i < boldSpans.length; i++) {
            if (boldSpans[i].innerText.toLowerCase().includes('not accepting applications')) {
                notAccepting = true;
                break;
            }
        }
        
        return {
            has_approved: bodyText.includes('approved'),
            has_selling_application: bodyText.includes('selling application'),
            has_request_approval: bodyText.includes('request approval'),
            has_submit: bodyText.includes('submit'),
            has_not_qualify: bodyText.includes('does not qualify'),
            has_not_accepting: notAccepting,
            has_error: bodyText.includes('error') || bodyText.includes('something went wrong')
        };
        """)
        
        # Attempt to click request approval button if text is present
        clicked_result = "Not attempted"
        if page_info.get('has_request_approval'):
            try:
                clicked_result = driver.execute_script("""
                    // Method 1: Find by data-csm attribute
                    var btn = document.querySelector('input[data-csm="saw-landing-page-request-approval-button-click"]');
                    if (btn && !btn.disabled) {
                        btn.click();
                        return 'Clicked by data-csm attribute';
                    }
                    
                    // Method 2: Find by class and text
                    var spans = document.querySelectorAll('span.a-button-text');
                    for (var i = 0; i < spans.length; i++) {
                        if (spans[i].innerText.toLowerCase().includes('request approval')) {
                            var parent = spans[i].closest('.a-button');
                            if (parent) {
                                var inputBtn = parent.querySelector('input.a-button-input');
                                if (inputBtn && !inputBtn.disabled) {
                                    inputBtn.click();
                                    return 'Clicked by finding text and closest input';
                                }
                            }
                        }
                    }
                    
                    // Method 3: Find button by text content
                    var allButtons = document.querySelectorAll('button, input[type="submit"], input[type="button"]');
                    for (var i = 0; i < allButtons.length; i++) {
                        var btnText = (allButtons[i].innerText || allButtons[i].value || '').toLowerCase();
                        if (btnText.includes('request approval') && !allButtons[i].disabled) {
                            allButtons[i].click();
                            return 'Clicked by button text search';
                        }
                    }
                    
                    // Method 4: Find by aria-label
                    var ariaButtons = document.querySelectorAll('[aria-label*="approval"], [aria-label*="request"]');
                    for (var i = 0; i < ariaButtons.length; i++) {
                        if (!ariaButtons[i].disabled) {
                            ariaButtons[i].click();
                            return 'Clicked by aria-label';
                        }
                    }
                    
                    return 'Button not found or disabled';
                """)
                if "Clicked" in str(clicked_result):
                    time.sleep(3)
            except Exception as e:
                print(f"  Error clicking request approval button: {e}")
        
        if "Clicked" in str(clicked_result):
            # print(f"  Successfully clicked Request approval button")
            check_and_log_document_requirements(driver, asin, title, sku, worksheet)
        elif page_info.get('has_approved'):
            print(f"  ASIN {asin}: Already approved")
            if worksheet and not asin_exists_in_sheet(worksheet, asin):
                try: 
                    worksheet.append_row([asin, sku, title, 'approved'])
                    print(f"  Saved to Google Sheet: {asin} -> approved")
                except: pass
            elif worksheet:
                print(f"  SKIP: {asin} already in sheet")
        elif page_info.get('has_not_accepting'):
            print(f"  ASIN {asin}: Not accepting applications")
            if worksheet and not asin_exists_in_sheet(worksheet, asin):
                try: 
                    worksheet.append_row([asin, sku, title, 'not_accepting_applications'])
                    print(f"  Saved to Google Sheet: {asin} -> not_accepting_applications")
                except: pass
            elif worksheet:
                print(f"  SKIP: {asin} already in sheet")
        elif page_info.get('has_not_qualify'):
            print(f"  ASIN {asin}: Account does not qualify")
            if worksheet and not asin_exists_in_sheet(worksheet, asin):
                try: 
                    worksheet.append_row([asin, sku, title, 'does_not_qualify'])
                    print(f"  Saved to Google Sheet: {asin} -> does_not_qualify")
                except: pass
            elif worksheet:
                print(f"  SKIP: {asin} already in sheet")
        elif page_info.get('has_selling_application'):
            print(f"  ASIN {asin}: Selling application page loaded")
            check_and_log_document_requirements(driver, asin, title, sku, worksheet)
        elif page_info.get('has_request_approval'):
            print(f"  ASIN {asin}: Request approval text found, but button missing or disabled")
        else:
            print(f"  ASIN {asin}: Unknown page state")
        
    except Exception as e:
        print(f"  Error checking page: {e}")
    
    return True




def process_row(profile, worksheet=None, df_worksheet=None):
    result = {'success': False, 'processed': 0, 'skipped': 0, 'pages': 0, 'error': None}
    print(f"Store: {profile.get('profile_name', 'Unknown')}")

    # Launch browser
    driver, gl = load_web_driver_with_gologin(profile['profile_id'])

    try:
        # Get base URL from store config
        amazon_home = profile.get('Amazon Home Page Link', 'https://sellercentral.amazon.com/home')
        base_url = amazon_home.replace("home", "")
        
        # Open first page with approval required filter
        open_approval_required_inventory(driver, base_url, page_number=1)

        # Close extra tabs
        main_handle = driver.current_window_handle
        for handle in driver.window_handles:
            if handle != main_handle:
                try:
                    driver.switch_to.window(handle)
                    driver.close()
                except:
                    pass
        driver.switch_to.window(main_handle)

        # Generate temporary log identifier for terminal output
        store_name = str(profile.get('profile_name', 'Unknown')).strip()
        print(f"Initiating process for store: {store_name}")

        # Load processed ASINs from today's Google Sheet (current worksheet)
        all_processed_asins = set()
        
        if df_worksheet is not None and not df_worksheet.empty and 'ASIN' in df_worksheet.columns:
            today_asins = set(df_worksheet['ASIN'].astype(str).str.strip().tolist())
            all_processed_asins.update(today_asins)
            print(f"  {len(today_asins)} ASINs already processed today.")
        else:
            print(f"  Fresh start - no ASINs processed yet.")
        current_page = 1
        total_processed = 0
        total_skipped = 0

        while True:
            # print(f"\n{'='*50}")
            print(f"  PAGE {current_page}")
            # print(f"{'='*50}")

            # For pages after the first, navigate to the next page
            if current_page > 1:
                open_approval_required_inventory(driver, base_url, page_number=current_page)

            # Count products on current page using div[data-sku] selector
            product_count = driver.execute_script("""
                var rows = document.querySelectorAll('div[data-sku]');
                return rows.length;
            """)
            
            print(f"  Products found on page {current_page}: {product_count}")
            
            if product_count == 0:
                print(f"  No products found on page {current_page}. All pages processed!")
                break

            # Process each product one by one
            for idx in range(product_count):
                print(f"\n  Processing product {idx + 1} of {product_count}...")
                
                # No page refresh - just click Nth product on the same page
                product_result = extract_first_product_and_click_fix_listing(driver, product_index=idx)
                
                if product_result and product_result.get('success'):
                    asin = product_result.get('asin')
                    sku = product_result.get('sku', 'Unknown')
                    title = product_result.get('title', 'Unknown')
                    
                    print(f"  Product {idx + 1}: ASIN={asin}, SKU={sku}")
                    
                    if asin in all_processed_asins:
                        print(f"  SKIP: {asin} already processed")
                        total_skipped += 1
                        continue
                    
                    time.sleep(3)
                    
                    handles_after = driver.window_handles
                    if len(handles_after) > 1:
                        new_tab = [h for h in handles_after if h != main_handle][-1]
                        driver.switch_to.window(new_tab)
                    
                    time.sleep(3)
                    process_approval_page(driver, asin, title, sku, worksheet)
                    
                    try:
                        current_handles = driver.window_handles
                        if len(current_handles) > 1:
                            for h in current_handles:
                                if h != main_handle:
                                    try:
                                        driver.switch_to.window(h)
                                        driver.close()
                                    except: pass
                        driver.switch_to.window(main_handle)
                    except Exception as tab_err:
                        print(f"  Error returning to inventory: {tab_err}")
                    
                    all_processed_asins.add(asin)
                    total_processed += 1
                else:
                    print(f"  Failed to extract or click product")
                    break
                
                time.sleep(2)

            # Move to next page
            current_page += 1

        # ====== SUMMARY ======
        print(f"\n{'='*50}")
        print(f"  Execution Complete. Summary:")
        print(f"  Total pages scanned: {current_page}")
        print(f"  Total ASINs processed: {total_processed}")
        print(f"  Total ASINs skipped (duplicates): {total_skipped}")
        print(f"{'='*50}")

    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"Error: {e}")
        result['error'] = str(e)
    finally:
        for handle in driver.window_handles:
            try:
                driver.switch_to.window(handle)
                driver.close()
            except:
                pass
        return result

def get_local_stores():
    """Fetch store data from local stores.csv file. Only used when settings.LOCAL is True."""
    try:
        df = pd.read_csv('stores.csv')
        print(f"Loaded {len(df)} stores from stores.csv")
    except Exception as e:
        print(f"Error reading stores.csv: {e}")
        return None
    
    active = df[df['status'] == 1]

    if len(active) == 0:
        print("No active stores in stores.csv")
        return None

    return active


def main():

    if not settings.LOCAL:
        print("LOCAL mode is disabled. Store data will be fetched from Google Sheets.")
        print("Please run approval.py instead.")
        return

    # LOCAL mode: fetch stores from stores.csv
    active = get_local_stores()
    if active is None:
        return

    profile = active.iloc[0]
    print(f"Active store found: {profile.get('profile_name', 'Unknown')}")
    
    # Setup Google Sheets and Drive
    worksheet = None
    df_worksheet = None
    
    try:
        # Import from approval.py (local import to avoid circular dependency)
        from approval import authenticate_gspread, authenticate_pydrive, get_or_create_folder, get_or_create_sheet_in_folder
        
        print("\nAuthenticating with Google Sheets and Drive...")
        gc = authenticate_gspread()
        drive = authenticate_pydrive()
        print("Authentication successful")
        
        # Get or create "Bot Approval Local" folder
        print("\nSetting up Bot Approval Local folder...")
        bot_files_folder_id = get_or_create_folder("Bot Approval Local", drive)
        
        if bot_files_folder_id:
            # Create sheet name with current date
            current_date = datetime.now().strftime('%Y-%m-%d')
            sheet_name = f"{profile['profile_name']}_{current_date}"
            
            print(f"Creating/accessing sheet: {sheet_name}")
            
            # Get or create sheet in folder
            sheet_id = get_or_create_sheet_in_folder(sheet_name, bot_files_folder_id, drive)
            sh = gc.open_by_key(sheet_id)
            
            # Get or create the first worksheet
            try:
                worksheet = sh.get_worksheet(0)
            except:
                worksheet = sh.add_worksheet(title="Sheet1", rows="1000000", cols="4")
            
            # Check if header exists, if not write it
            header = worksheet.row_values(1)
            if not header or 'ASIN' not in header:
                worksheet.insert_row(['ASIN', 'SKU', 'Title', 'Status'], 1)
                print("Header row created in sheet")
            
            # Load existing records for duplicate checking
            records = worksheet.get_all_records()
            df_worksheet = pd.DataFrame(records) if records else pd.DataFrame(columns=['ASIN', 'SKU', 'Title', 'Status'])
            
            print(f"Connected to Google Sheet: {sheet_name}")
            print(f"Sheet URL: https://docs.google.com/spreadsheets/d/{sheet_id}")
            print(f"Existing records in sheet: {len(df_worksheet)}")
        else:
            print("Error: Could not create/access Bot Approval Local folder")
            
    except Exception as e:
        print(f"Error setting up Google Sheets: {e}")
        import traceback
        traceback.print_exc()
        print("\nContinuing without Google Sheets (data will not be saved)...")
    
    # Process the store
    print("\n" + "="*60)
    print("Starting store processing...")
    print("="*60 + "\n")
    
    try:
        process_row(profile, worksheet, df_worksheet)
    except Exception as e:
        print(f"\nError during processing: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    main()