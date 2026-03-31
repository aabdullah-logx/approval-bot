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
import pandas as pd
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


def load_web_driver_with_gologin(profile_id):
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

    if platform == "win32":
        local_chromedriver_path = os.getenv('CHROMEDRIVER_WINDOWS', 'chromedriver.exe')
    elif platform in ("linux", "linux2"):
        local_chromedriver_path = os.getenv('CHROMEDRIVER_LINUX', './chromedriver_linux')
    else:
        local_chromedriver_path = os.getenv('CHROMEDRIVER_MAC', './chromedriver')

    driver = webdriver.Chrome(service=Service(local_chromedriver_path), options=chrome_options)
    return driver, gl


def extract_asins(driver):
    """Extract all Inactive ASINs from the current inventory page."""
    
    print("\nExtracting ASINs from page...")
    
    asins_info = driver.execute_script(r"""
    var asins_info = {};
    var seen = {};
    var debugInfo = [];

    // Noise words that are NOT part of a title or SKU
    var NOISE_WORDS = ['inactive', 'active', 'performance', 'price', 'quantity',
                       'available', 'fix listing', 'approval', 'status', 'suppressed',
                       'stranded', 'your price', 'net proceeds', 'days', 'units',
                       'issues', 'listing', 'fee', 'condition', 'new', 'used',
                       'edit', 'delete', 'close', 'more', 'add a product'];

    function isNoise(line) {
        var low = line.toLowerCase().trim();
        if (low.length < 5) return true;
        for (var n = 0; n < NOISE_WORDS.length; n++) {
            if (low === NOISE_WORDS[n]) return true;
        }
        // Skip lines that are just numbers, currency, dates or very short
        if (/^[\$\d\.\,\%\s\-\/]+$/.test(line)) return true;
        // Skip if starts with ASIN or SKU
        if (/^(ASIN|SKU)/i.test(low)) return true;
        return false;
    }

    function findRows() {
        var rawRows = document.querySelectorAll('tr, mt-row, [role="row"], .mt-row, .kat-table-row');
        if (rawRows.length > 0) return rawRows;
        return [document.body];
    }

    function getTitleFromLines(lines, asinLineIdx) {
        var title = 'Unknown';
        if (asinLineIdx > 0) {
            var titleCandidates = [];
            for (var j = 0; j < asinLineIdx; j++) {
                var candidate = lines[j].trim();
                if (!isNoise(candidate) && candidate.length > 8) {
                    titleCandidates.push(candidate);
                }
            }
            if (titleCandidates.length > 0) {
                title = titleCandidates.reduce(function(a, b){ return a.length >= b.length ? a : b; });
                title = title.substring(0, 200);
            }
        }
        return title;
    }

    // Build ASIN -> Title from product links like https://www.amazon.ca/dp/B09SPRN8GD
    var asinTitleMap = {};
    var productAnchors = document.querySelectorAll('a[href*="/dp/"], a[href*="/gp/product/"]');
    for (var p = 0; p < productAnchors.length; p++) {
        var hrefP = productAnchors[p].getAttribute('href') || '';
        var asinFromDp = hrefP.match(/\/dp\/([A-Z0-9]{10})(?:[\/?#]|$)/i);
        var asinFromGp = hrefP.match(/\/gp\/product\/([A-Z0-9]{10})(?:[\/?#]|$)/i);
        var asinP = asinFromDp ? asinFromDp[1] : (asinFromGp ? asinFromGp[1] : null);
        if (!asinP) continue;

        asinP = asinP.toUpperCase();
        var titleP = (productAnchors[p].innerText || '').trim();
        if (!titleP || isNoise(titleP) || titleP.length < 8) continue;

        if (!asinTitleMap[asinP] || titleP.length > asinTitleMap[asinP].length) {
            asinTitleMap[asinP] = titleP.substring(0, 200);
        }
    }

    // Build ASIN -> SKU by starting from each SKU link, then finding ASIN in its nearest product container.
    var asinSkuMap = {};
    var skuAnchors = document.querySelectorAll('a[href*="mSku="]');
    for (var x = 0; x < skuAnchors.length; x++) {
        var hrefX = skuAnchors[x].getAttribute('href') || '';
        var skuMatchX = hrefX.match(/[?&]mSku=([^&#]+)/i);
        if (!skuMatchX || !skuMatchX[1]) continue;

        var skuValue = decodeURIComponent(skuMatchX[1]).trim().substring(0, 100);
        if (!skuValue) continue;

        var container = skuAnchors[x].closest('tr, mt-row, [role="row"], .mt-row, .kat-table-row, li, .a-row, .a-section');
        var probe = container || skuAnchors[x].parentElement;
        var asinInContainer = null;
        var containerText = '';

        // Walk up a few levels to find the nearest node that contains ASIN text.
        for (var depth = 0; depth < 8 && probe; depth++) {
            containerText = probe.innerText || '';
            asinInContainer = containerText.match(/ASIN[\s:]*([A-Z0-9]{10})/i);
            if (asinInContainer && asinInContainer[1]) {
                break;
            }
            probe = probe.parentElement;
        }

        if (asinInContainer && asinInContainer[1]) {
            var mappedAsin = asinInContainer[1].toUpperCase();
            asinSkuMap[mappedAsin] = skuValue;

            if (!seen[mappedAsin]) {
                seen[mappedAsin] = true;
                var linesX = containerText
                    .split(/\r?\n/)
                    .map(function(l){ return l.trim(); })
                    .filter(function(l){ return l.length > 0; });

                var asinLineIdxX = -1;
                for (var ix = 0; ix < linesX.length; ix++) {
                    if (linesX[ix].indexOf(mappedAsin) !== -1 && /ASIN/i.test(linesX[ix])) {
                        asinLineIdxX = ix;
                        break;
                    }
                }

                var titleX = asinTitleMap[mappedAsin] || getTitleFromLines(linesX, asinLineIdxX);
                titleX = titleX.replace(/,/g, ' ');
                asins_info[mappedAsin] = {'sku': skuValue.replace(/,/g, ' '), 'title': titleX};
            }
        }
    }

    var rows = findRows();
    debugInfo.push('Total rows found: ' + rows.length);
    debugInfo.push('ASIN->Title links mapped: ' + Object.keys(asinTitleMap).length);
    debugInfo.push('ASIN->SKU links mapped: ' + Object.keys(asinSkuMap).length);

    rows.forEach(function(r) {
        var txt = r.innerText || '';
        if (txt.indexOf('ASIN') === -1) return;

        // Split by newlines (handles \n and \r\n)
        var lines = txt.split(/\r?\n/).map(function(l){ return l.trim(); }).filter(function(l){ return l.length > 0; });

        // Find ASINs using broad search on full text (like the old working code)
        var asinRegex = /ASIN[\s:]*([A-Z0-9]{10})/gi;
        var match;
        while ((match = asinRegex.exec(txt)) !== null) {
            var asin = match[1].toUpperCase();
            if (seen[asin]) continue;
            seen[asin] = true;

            // Find which line index contains this ASIN
            var asinLineIdx = -1;
            for (var i = 0; i < lines.length; i++) {
                if (lines[i].indexOf(asin) !== -1 && /ASIN/i.test(lines[i])) {
                    asinLineIdx = i;
                    break;
                }
            }

            debugInfo.push('ASIN ' + asin + ' found at line index ' + asinLineIdx + ' of ' + lines.length);
            if (asinLineIdx >= 0 && asinLineIdx < 5) {
                debugInfo.push('  Lines around ASIN: ' + JSON.stringify(lines.slice(0, Math.min(asinLineIdx + 4, lines.length))));
            }

            // --- Extract SKU ---
            var sku = asinSkuMap[asin] || 'Unknown';

            // Priority 1 fallback: find SKU from skucentral link in the same row/container
            if (sku === 'Unknown') {
                var rowLinks = r.querySelectorAll('a[href*="mSku="]');
                for (var a = 0; a < rowLinks.length; a++) {
                    var href = rowLinks[a].getAttribute('href') || '';
                    var skuFromHref = href.match(/[?&]mSku=([^&#]+)/i);
                    if (skuFromHref && skuFromHref[1]) {
                        sku = decodeURIComponent(skuFromHref[1]).trim().substring(0, 100);
                        break;
                    }
                    var linkText = (rowLinks[a].innerText || '').trim();
                    if (linkText && /^[A-Z0-9\-_]{6,}$/i.test(linkText)) {
                        sku = linkText.substring(0, 100);
                        break;
                    }
                }
            }

            // Priority 2 (fallback): search lines near/after the ASIN line for SKU label
            if (sku === 'Unknown') {
                var searchStart = Math.max(0, asinLineIdx);
                var searchEnd = Math.min(lines.length, asinLineIdx + 5);
                for (var s = searchStart; s < searchEnd; s++) {
                    var skuMatch = lines[s].match(/SKU[\s:]+(.+)/i);
                    if (skuMatch) {
                        var rawSku = skuMatch[1].trim();
                        // Take only first chunk (stop at double-space or tab)
                        var skuParts = rawSku.split(/\s{2,}|\t/);
                        sku = skuParts[0].trim().substring(0, 100);
                        break;
                    }
                }
            }

            // --- Extract Title ---
            // Title is typically BEFORE the ASIN line in the row text
            var title = asinTitleMap[asin] || getTitleFromLines(lines, asinLineIdx);

            title = title.replace(/,/g, ' ');
            sku   = sku.replace(/,/g, ' ');

            asins_info[asin] = {'sku': sku, 'title': title};
        }
    });

    // Fallback: scan HTML for ASINs if nothing found via row parsing
    if (Object.keys(asins_info).length === 0) {
        debugInfo.push('FALLBACK: No ASINs from rows, scanning HTML...');
        var htmlText = document.body.innerHTML || '';
        var regex2 = /asin[=:\s"']+([A-Z0-9]{10})/gi;
        var match2;
        while ((match2 = regex2.exec(htmlText)) !== null) {
            var asin2 = match2[1].toUpperCase();
            if (!seen[asin2]) {
                seen[asin2] = true;
                asins_info[asin2] = {'sku': 'Unknown', 'title': 'Unknown'};
            }
        }
    }

    return {'data': asins_info, 'debug': debugInfo};
    """)
    
    # Print debug info
    debug = asins_info.get('debug', [])
    for d in debug:
        print(f"  [DEBUG] {d}")
    
    actual_data = asins_info.get('data', {})
    print(f"  Found {len(actual_data)} ASINs mapping.")
    
    # Print first few entries for verification
    for asin, info in list(actual_data.items())[:3]:
        print(f"    {asin} -> Title: {info.get('title','?')[:60]}  |  SKU: {info.get('sku','?')}")
    
    return actual_data


def check_and_log_document_requirements(driver, asin, title, sku, worksheet=None):
    """Check what documents are required on the current page and log to Google Sheets."""
    try:
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
        # print(f"ASIN {asin} Documents required: {doc_string} -> Logged as: {status}")
        
        # Log to worksheet if available
        if worksheet:
            try:
                worksheet.append_row([asin, sku, title, status])
            except Exception as w_err:
                print(f"  Error appending to worksheet: {w_err}")
            
    except Exception as e:
        print(f"  Error checking documents: {e}")


def process_approval_for_asin(driver, asin, base_url, info, worksheet=None):
    """Navigate directly to the approval URL for a given ASIN."""
    
    title = info.get('title', 'Unknown')
    sku = info.get('sku', 'Unknown')
    
    approval_url = f"{base_url}hz/approvalrequest/restrictions/approve?asin={asin}&itemcondition=New"
    print(f"\n  Opening approval page for ASIN {asin}...")
    # print(f"  URL: {approval_url}")
    
    driver.get(approval_url)
    time.sleep(5)
    
    # Check what page we landed on
    current_url = driver.current_url
    page_title = driver.title
    # print(f"  Current URL: {current_url}")
    # print(f"  Page title: {page_title}")
    
    # Check page content
    try:
        page_info = driver.execute_script("""
        var bodyText = document.body.innerText.toLowerCase();
        return {
            has_approved: bodyText.includes('approved'),
            has_selling_application: bodyText.includes('selling application'),
            has_request_approval: bodyText.includes('request approval'),
            has_submit: bodyText.includes('submit'),
            has_not_qualify: bodyText.includes('does not qualify'),
            has_error: bodyText.includes('error') || bodyText.includes('something went wrong'),
            snippet: document.body.innerText.substring(0, 300)
        };
        """)
        
        # Attempt to click request approval button if text is present
        clicked_result = "Not attempted"
        if page_info.get('has_request_approval'):
            try:
                clicked_result = driver.execute_script("""
                    // Method 1: finding by data-csm attribute
                    var btn = document.querySelector('input[data-csm="saw-landing-page-request-approval-button-click"]');
                    if (btn) {
                        btn.click();
                        return 'Clicked by data-csm attribute';
                    }
                    
                    // Method 2: finding by class and text
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
                    return 'Button not found';
                """)
                if "Clicked" in str(clicked_result):
                    time.sleep(3) # wait for next page/action to load
            except Exception as e:
                pass
        
        if "Clicked" in str(clicked_result):
            # print(f"  ASIN {asin}: Clicked 'Request approval' ({clicked_result})")
            check_and_log_document_requirements(driver, asin, title, sku, worksheet)
        elif page_info.get('has_approved'):
            print(f" ASIN {asin}: Already approved or approval page loaded!")
            if worksheet:
                try: worksheet.append_row([asin, sku, title, 'approved'])
                except: pass
        elif page_info.get('has_not_qualify'):
            print(f"  ASIN {asin}: Account does not qualify")
            if worksheet:
                try: worksheet.append_row([asin, sku, title, 'does_not_qualify'])
                except: pass
        elif page_info.get('has_selling_application'):
            print(f"  ASIN {asin}: Selling application page loaded")
            check_and_log_document_requirements(driver, asin, title, sku, worksheet)
        elif page_info.get('has_request_approval'):
            print(f"   ASIN {asin}: Request approval text found, but button missing or disabled.")
        else:
            print(f"   ASIN {asin}: Page loaded, check snippet below")
        
        # print(f"  Page snippet: {page_info.get('snippet', 'N/A')[:200]}")
        
    except Exception as e:
        print(f"  Error checking page: {e}")
    
    return True


def get_processed_asins_from_csv(csv_filename):
    """(Deprecated) Local CSV storage has been disabled."""
    return set()


def process_row(profile, worksheet=None, df_worksheet=None):
    result = {'success': False, 'processed': 0, 'skipped': 0, 'pages': 0, 'error': None}
    print(f"Store: {profile.get('profile_name', 'Unknown')}")

    # Launch browser
    driver, gl = load_web_driver_with_gologin(profile['profile_id'])

    try:
        # Get base URL from store config
        amazon_home = profile.get('Amazon Home Page Link', 'https://sellercentral.amazon.com/home')
        base_url = amazon_home.replace("home", "")
        
        # Build URL with status=approval_required directly (no need for dropdown filter)
        page_size = 10
        base_inventory_url = f"{base_url}myinventory/inventory/views/fix-issues?fulfilledBy=all&pageSize={page_size}&sort=date_created_desc&status=approval_required"

        # First page load
        first_page_url = f"{base_inventory_url}&page=1"
        print(f"Opening: {first_page_url}")
        driver.get(first_page_url)
        time.sleep(5)

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

        # Load processed ASINs only from today's sheet (current worksheet)
        # This ensures each day gets fresh processing, but prevents duplicates within same day
        all_processed_asins = set()
        
        if df_worksheet is not None and not df_worksheet.empty and 'ASIN' in df_worksheet.columns:
            today_asins = set(df_worksheet['ASIN'].astype(str).str.strip().tolist())
            all_processed_asins.update(today_asins)
            print(f"  Loaded {len(today_asins)} ASINs from today's sheet (will skip duplicates within same day).")
            
        if all_processed_asins:
            print(f"  Total {len(all_processed_asins)} ASINs already processed today.")
        else:
            print(f"  Fresh start - no ASINs processed yet today.")
        current_page = 1
        total_processed = 0
        total_skipped = 0

        while True:
            print(f"\n{'='*50}")
            print(f"  PAGE {current_page}")
            print(f"{'='*50}")

            # For pages after the first, navigate to the next page
            if current_page > 1:
                next_page_url = f"{base_inventory_url}&page={current_page}"
                print(f"  Navigating to page {current_page}...")
                driver.get(next_page_url)
                time.sleep(6)

            # Extract ASINs from current page
            asins_info = extract_asins(driver)

            if not asins_info:
                print(f"  No ASINs found on page {current_page}. All pages processed!")
                break

            # Filter out already processed ASINs (duplicate check)
            new_asins = {}
            for asin, info in asins_info.items():
                if asin in all_processed_asins:
                    print(f"  SKIP (duplicate): {asin} already processed")
                    total_skipped += 1
                else:
                    new_asins[asin] = info

            if not new_asins:
                print(f"  All ASINs on page {current_page} are duplicates. Moving to next page.")
                current_page += 1
                continue

            print(f"  New ASINs to process on page {current_page}: {len(new_asins)}")

            # Process each new ASIN
            for asin, info in new_asins.items():
                process_approval_for_asin(driver, asin, base_url, info, worksheet)
                all_processed_asins.add(asin)
                total_processed += 1
                time.sleep(1.5)

            # Move to next page
            current_page += 1

        # ====== SUMMARY ======
        print(f"\n{'='*50}")
        print(f"  Execution Complete. Summary:")
        print(f"  Total pages scanned: {current_page}")
        print(f"  Total ASINs processed: {total_processed}")
        print(f"  Total ASINs skipped (duplicates): {total_skipped}")
        print(f"{'='*50}")

        # Keep browser open so user can see result
        print("\nKeeping browser open for 8 seconds...")
        time.sleep(8)
        
        result['success'] = True
        result['processed'] = total_processed
        result['skipped'] = total_skipped
        result['pages'] = current_page

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
        try:
            driver.quit()
        except:
            pass
        return result

def main():
    df = pd.read_csv('stores.csv')
    active = df[df['status'] == 1]

    if len(active) == 0:
        print("No active stores in stores.csv")
        return

    profile = active.iloc[0]
    process_row(profile)

if __name__ == '__main__':
    main()
    