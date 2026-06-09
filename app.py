import os
import asyncio
from flask import Flask, render_template, request, jsonify
from playwright.async_api import async_playwright

app = Flask(__name__)

async def scrape_gmaps(keyword, location, max_results):
    leads = []
    async with async_playwright() as p:
        # --headless=new এবং কম র‍্যাম ব্যবহারের জন্য নিচের আর্গুমেন্টগুলো জরুরি
        browser = await p.chromium.launch(
            headless=True,
            args=[
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
                '--disable-accelerated-2d-canvas',
                '--no-first-run',
                '--no-zygote',
                '--single-process', # র‍্যাম বাঁচানোর জন্য সবচেয়ে গুরুত্বপূর্ণ
                '--disable-gpu'
            ]
        )
        
        # নতুন ব্রাউজার কনটেক্সট (র‍্যাম ও ব্যান্ডউইথ বাঁচাতে ইমেজ লোড বন্ধ রাখা)
        context = await browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
        await context.route("**/*.{png,jpg,jpeg,gif,webp,svg,mp4,css,woff,woff2}", lambda route: route.abort())
        
        page = await context.new_page()
        
        try:
            search_url = f"https://www.google.com/maps/search/{keyword}+{location}"
            await page.goto(search_url, timeout=60000)
            await page.wait_for_timeout(3000)
            
            # এখানে আপনার ক্লটের স্ক্র্যাপিং লজিকটি বসবে (যেমন কার্ড স্ক্রোল করা)
            # এটি একটি ডামি স্যাম্পল রেসপন্স সার্ভার চেক করার জন্য:
            leads = [
                {
                    "name": f"Sample {keyword} Business",
                    "phone": "+1 234 567 890",
                    "website": "No Website",
                    "email": "info@sample.com",
                    "facebook": ""
                }
            ]
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
    max_results = int(data.get('results', 20))
    
    try:
        # অ্যাসিঙ্ক ফাংশন রান করা
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        results = loop.run_until_complete(scrape_gmaps(keyword, location, max_results))
        return jsonify(results)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port, threaded=True)
