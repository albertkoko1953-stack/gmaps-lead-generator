import os
import asyncio
import re
from flask import Flask, render_template, request, jsonify
from playwright.async_api import async_playwright

app = Flask(__name__)

async def extract_email_and_socials(page, url):
    """ওয়েবসাইট ভিজিট করে ইমেইল এবং সোশ্যাল মিডিয়া লিংক খোঁজার ফাংশন"""
    if not url or url.lower() == 'no website' or 'google.com' in url:
        return "No Email", ""
    
    try:
        # মেইন ডোমেইন ঠিক করা
        if not url.startswith('http'):
            url = 'https://' + url
            
        await page.goto(url, timeout=15000, wait_until="domcontentloaded")
        content = await page.content()
        
        # ইমেইল খোঁজার সাধারণ রেগুলার এক্সপ্রেশন
        emails = re.findall(r'[a-zA-Z0-9 Mildred._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,4}', content)
        email = emails[0] if emails else "No Email"
        
        # ফেসবুক লিংক খোঁজার লজিক
        fb_match = re.search(r'href="(https?://(www\.)?facebook\.com/[^"\s]+)"', content)
        facebook = fb_match.group(1) if fb_match else ""
        
        return email, facebook
    except:
        return "No Email", ""

async def scrape_gmaps(keyword, location, max_results):
    leads = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
                '--disable-gpu',
                '--single-process' # Render এর সীমিত র‍্যামের জন্য অত্যন্ত জরুরি
            ]
        )
        
        # গুগলকে আসল ব্রাউজার বোঝানোর জন্য রিয়েল ইউজার এজেন্ট ও লোকেশন সেট করা
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 720},
            locale="en-US"
        )
        
        # সাইটের বাড়তি ইমেজ লোড বন্ধ করে মেমরি ও স্পিড বাঁচানো
        await context.route("**/*.{png,jpg,jpeg,gif,webp,svg,mp4,css,woff,woff2}", lambda route: route.abort())
        
        page = await context.new_page()
        
        try:
            # গুগল ম্যাপসের অফিশিয়াল সার্চ ইউআরএল ফরম্যাট
            search_query = f"{keyword} in {location}"
            search_url = f"https://www.google.com/maps/search/{search_query.replace(' ', '+')}"
            
            await page.goto(search_url, timeout=60000, wait_until="networkidle")
            await page.wait_for_timeout(3000)
            
            # বাম পাশের রেজাল্ট প্যানেলটি স্ক্রোল করার লজিক (ডাটা লোড করার জন্য)
            panel_selector = '.m676Xb' # গুগল ম্যাপসের রেজাল্ট বক্সের ক্লাসের সাধারণ সিলেক্টর
            panel = await page.query_selector('div[role="feed"]')
            
            scroll_count = 0
            while scroll_count < 3 and len(leads) < max_results:
                if panel:
                    await page.evaluate('(el) => el.scrollTop = el.scrollHeight', panel)
                    await page.wait_for_timeout(2000)
                scroll_count += 1
            
            # গুগল ম্যাপসের প্রতিটা বিজনেস এন্ট্রির লেটেস্ট ২০২৬ সিলেক্টর
            cards = await page.query_selector_all('div[role="article"]')
            
            for card in cards:
                if len(leads) >= max_results:
                    break
                    
                try:
                    # ১. বিজনেসের নাম
                    name_el = await card.query_selector('div.qBF1Pd')
                    name = await name_el.inner_text() if name_el else "Unknown Business"
                    
                    # ২. ফোন নাম্বার ও অ্যাড্রেস রিড করার চেষ্টা করা
                    phone = "No Phone"
                    address = "No Address"
                    
                    # ম্যাপের কার্ডের ভেতরের সব টেক্সট লাইন বাই লাইন দেখা
                    full_text = await card.inner_text()
                    lines = full_text.split('\n')
                    
                    for line in lines:
                        if re.search(r'\+?[0-9]{1,4}[-\s]?\(?[0-9]{1,3}\)?[-\s]?[0-9]{3,4}[-\s]?[0-9]{3,4}', line):
                            phone = line
                        elif any(word in line.lower() for word in ['st', 'ave', 'rd', 'blvd', 'suite', 'highway', 'usa']):
                            address = line
                    
                    # ৩. ওয়েবসাইট লিঙ্ক এক্সট্রাক্ট করা
                    website_el = await card.query_selector('a[data-value="Website"]')
                    website = await website_el.get_attribute('href') if website_el else "No Website"
                    
                    leads.append({
                        "name": name,
                        "phone": phone,
                        "website": website,
                        "address": address,
                        "email": "Pending...",
                        "facebook": ""
                    })
                except Exception as card_err:
                    print(f"Error reading card: {card_err}")
                    continue
            
            # ৪. অ্যাডভান্সড ফিচার: যেসব লিডের ওয়েবসাইট আছে, তাদের থেকে ইমেইল ও ফেসবুক বের করা
            enrich_page = await context.new_page()
            for lead in leads:
                if lead["website"] != "No Website":
                    email, facebook = await extract_email_and_socials(enrich_page, lead["website"])
                    lead["email"] = email
                    lead["facebook"] = facebook
                else:
                    lead["email"] = "No Email"
                    
        except Exception as e:
            print(f"Scraping error: {e}")
        finally:
            await browser.close()
            
    return leads

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/scrape', methods=['POST'])
def scrape():
    data = request.get_json() or {}
    keyword = data.get('keyword', 'Dentists')
    location = data.get('location', 'Miami')
    max_results = int(data.get('results', 10)) # মেমরি বাঁচাতে ডিফল্ট ১০টি করে ডাটা রাখা হয়েছে
    
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        results = loop.run_until_complete(scrape_gmaps(keyword, location, max_results))
        return jsonify(results)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port, threaded=True)
